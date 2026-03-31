"""
agent.py
--------
Text-to-SQL LangChain agent for the e-commerce analytics database.

Architecture:
  1. User sends a natural language question
  2. Agent injects schema context + question into a prompt
  3. LLM generates a SQL SELECT query
  4. Safety check — reject any non-SELECT statement
  5. Execute SQL against SQLite
  6. If execution fails → retry once with the error message injected
  7. Format results into a plain-English answer via LLM
  8. Return the answer + the SQL that produced it

Design decisions:
  - Custom tool-based approach instead of SQLDatabaseChain
    Reason: gives explicit control over safety, retry logic, and formatting
  - Schema injected via system prompt — not retrieved dynamically
    Reason: schema is small (4 tables) and stable; injection is more reliable
  - Single retry cycle — sufficient for syntax errors and column name mistakes
  - All SQL execution is read-only — PRAGMA query_only = ON enforced at connection time
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.prompts import (
    SYSTEM_PROMPT,
    SQL_GENERATION_PROMPT,
    RETRY_PROMPT,
    ANSWER_FORMAT_PROMPT,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "ecommerce.db"

# SQL keywords that indicate a mutating operation
BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter",
    "create", "replace", "truncate", "attach", "detach",
    "pragma", "vacuum",
}


# ─────────────────────────────────────────────────────────────
# DATABASE CONNECTION
# ─────────────────────────────────────────────────────────────

def _get_readonly_connection() -> sqlite3.Connection:
    """
    Open a read-only SQLite connection.
    PRAGMA query_only = ON prevents any write operations at the
    database engine level — a second line of defence after our
    keyword check.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────
# SAFETY CHECK
# ─────────────────────────────────────────────────────────────

def _is_safe_sql(sql: str) -> tuple[bool, str]:
    """
    Check that the SQL is a SELECT-only statement.

    Returns (True, "") if safe.
    Returns (False, reason) if unsafe.

    Two-layer check:
      1. Keyword scan — catches obvious mutations
      2. Must start with SELECT after stripping whitespace/comments
    """
    # Strip SQL comments before checking
    stripped = re.sub(r"--[^\n]*", "", sql)       # single-line comments
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)  # block comments
    stripped = stripped.strip().lower()

    # Must start with SELECT
    if not stripped.startswith("select"):
        return False, f"Query does not start with SELECT. Got: '{stripped[:30]}...'"

    # Scan for blocked keywords (as whole words, not substrings)
    for keyword in BLOCKED_KEYWORDS:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, stripped):
            return False, f"Blocked keyword detected: '{keyword.upper()}'"

    return True, ""


# ─────────────────────────────────────────────────────────────
# SQL EXECUTION
# ─────────────────────────────────────────────────────────────

def _execute_sql(sql: str) -> tuple[list[dict], Optional[str]]:
    """
    Execute a SQL query against the read-only database.

    Returns:
      (rows, None)         — on success, rows as list of dicts
      ([], error_message)  — on failure
    """
    try:
        conn = _get_readonly_connection()
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return rows, None
    except Exception as e:
        return [], str(e)


# ─────────────────────────────────────────────────────────────
# RESULT FORMATTING
# ─────────────────────────────────────────────────────────────

def _format_results_as_table(rows: list[dict]) -> str:
    """
    Format query results as a readable text table for the LLM
    answer-formatting prompt.
    Truncates to 20 rows to keep the prompt concise.
    """
    if not rows:
        return "No results returned."

    rows = rows[:20]
    headers = list(rows[0].keys())
    col_widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}

    header_line = " | ".join(h.ljust(col_widths[h]) for h in headers)
    divider     = "-+-".join("-" * col_widths[h] for h in headers)
    data_lines  = [
        " | ".join(str(r.get(h, "")).ljust(col_widths[h]) for h in headers)
        for r in rows
    ]

    return "\n".join([header_line, divider] + data_lines)


# ─────────────────────────────────────────────────────────────
# THE AGENT CLASS
# ─────────────────────────────────────────────────────────────

class TextToSQLAgent:
    """
    A LangChain-powered Text-to-SQL agent with:
      - Schema-injected system prompt
      - Safety validation (SELECT-only)
      - One retry cycle on SQL errors
      - LLM-formatted plain-English answers
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001", temperature: float = 0.0):
        """
        temperature=0 makes SQL generation deterministic —
        we want consistent, correct SQL, not creative variation.
        """
        self.llm = ChatAnthropic(model=model, temperature=temperature)
        self.system_message = SystemMessage(content=SYSTEM_PROMPT)
        logger.info(f"Agent initialised with model={model}")

    # ── Internal: call the LLM ─────────────────────────────

    def _call_llm(self, user_content: str) -> str:
        """Send a message to the LLM and return the text response."""
        messages = [
            self.system_message,
            HumanMessage(content=user_content),
        ]
        response = self.llm.invoke(messages)
        return response.content.strip()

    # ── Internal: clean LLM SQL output ────────────────────

    def _extract_sql(self, llm_output: str) -> str:
        """
        Clean the LLM's SQL output.
        LLMs sometimes wrap SQL in markdown fences (```sql ... ```)
        even when told not to. Strip them defensively.
        """
        # Remove markdown code fences
        cleaned = re.sub(r"```(?:sql)?", "", llm_output, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()

        # If the LLM prefixed with "SQL:" strip it
        if cleaned.upper().startswith("SQL:"):
            cleaned = cleaned[4:].strip()

        return cleaned

    # ── Internal: generate SQL ─────────────────────────────

    def _generate_sql(self, question: str) -> str:
        """Ask the LLM to generate SQL for the given question."""
        prompt = SQL_GENERATION_PROMPT.format(question=question)
        raw = self._call_llm(prompt)
        sql = self._extract_sql(raw)
        logger.info(f"Generated SQL:\n{sql}")
        return sql

    # ── Internal: retry with error context ────────────────

    def _retry_sql(self, question: str, failed_sql: str, error: str) -> str:
        """
        Ask the LLM to fix a failed SQL query.
        Injects the original SQL and the error message so the LLM
        can diagnose the specific problem.
        """
        logger.warning(f"SQL failed: {error}. Retrying...")
        prompt = RETRY_PROMPT.format(
            question=question,
            failed_sql=failed_sql,
            error_message=error,
        )
        raw = self._call_llm(prompt)
        sql = self._extract_sql(raw)
        logger.info(f"Retry SQL:\n{sql}")
        return sql

    # ── Internal: format answer ────────────────────────────

    def _format_answer(self, question: str, sql: str, rows: list[dict]) -> str:
        """
        Ask the LLM to turn raw query results into a plain-English answer.
        This is a separate LLM call so we get a well-written response
        rather than just dumping the raw table at the user.
        """
        results_table = _format_results_as_table(rows)
        prompt = ANSWER_FORMAT_PROMPT.format(
            question=question,
            sql=sql,
            results=results_table,
        )
        return self._call_llm(prompt)

    # ── Public: main entry point ───────────────────────────

    def ask(self, question: str) -> dict:
        """
        Process a natural language question end-to-end.

        Returns a dict with:
          question      : the original question
          sql           : the SQL that was executed
          rows          : raw result rows (list of dicts)
          answer        : plain-English formatted answer
          success       : True if a result was returned
          error         : error message if something went wrong
          retried       : True if a retry was needed
        """
        logger.info(f"\n{'=' * 55}")
        logger.info(f"Question: {question}")
        logger.info("=" * 55)

        result = {
            "question": question,
            "sql": "",
            "rows": [],
            "answer": "",
            "success": False,
            "error": None,
            "retried": False,
        }

        # ── Step 1: Generate SQL ───────────────────────────
        sql = self._generate_sql(question)
        result["sql"] = sql

        # ── Step 2: Safety check ───────────────────────────
        safe, reason = _is_safe_sql(sql)
        if not safe:
            msg = f"Query blocked for safety: {reason}"
            logger.warning(msg)
            result["error"] = msg
            result["answer"] = (
                f"I cannot execute that query. {reason}. "
                "I only execute SELECT queries that read data."
            )
            return result

        # ── Step 3: Execute SQL ────────────────────────────
        rows, error = _execute_sql(sql)

        # ── Step 4: Retry if failed ────────────────────────
        if error:
            retry_sql = self._retry_sql(question, sql, error)
            result["retried"] = True

            # Safety check on retry SQL too
            safe, reason = _is_safe_sql(retry_sql)
            if not safe:
                result["error"] = f"Retry query blocked for safety: {reason}"
                result["answer"] = "I was unable to generate a safe query for this question."
                return result

            rows, error = _execute_sql(retry_sql)
            result["sql"] = retry_sql   # report the successful SQL

            if error:
                # Both attempts failed
                result["error"] = error
                result["answer"] = (
                    f"I tried to answer your question but encountered a database error "
                    f"even after retrying. Error: {error}"
                )
                logger.error(f"Both SQL attempts failed. Final error: {error}")
                return result

        # ── Step 5: Format answer ──────────────────────────
        result["rows"]    = rows
        result["success"] = True

        if not rows:
            result["answer"] = "The query executed successfully but returned no results."
        else:
            result["answer"] = self._format_answer(question, result["sql"], rows)

        logger.info(f"Answer: {result['answer']}")
        return result