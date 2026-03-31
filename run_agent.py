"""
run_agent.py
------------
Entry point for Step 5: Text-to-SQL LangChain Agent.

Runs all 10 required test questions and saves output to logs/.

Usage:
    export OPENAI_API_KEY="sk-..."
    python run_agent.py

    # Or pass key inline:
    OPENAI_API_KEY="sk-..." python run_agent.py
"""

import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Logging setup ──────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode="w", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

# ── Check API key before importing agent ──────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    logger.error("ANTHROPIC_API_KEY environment variable is not set.")
    logger.error("Run: export ANTHROPIC_API_KEY='sk-ant-...'")
    sys.exit(1)

from src.agent.agent import TextToSQLAgent


# ── The 10 required test questions ────────────────────────
TEST_QUESTIONS = [
    "What are the top 5 products by total revenue?",
    "How many orders were placed in the last 6 months?",
    "Which customer has spent the most money overall?",
    "What is the average order value by product category?",
    "Show me the monthly revenue trend for the last year.",
    "Which products have an average rating below 3.0?",
    "What percentage of orders were cancelled?",
    "Find customers who have placed more than 5 orders.",
    "What is the most popular payment method?",
    "Which category has the highest revenue, and what is its best-selling product?",
]


def run_all_questions(agent: TextToSQLAgent) -> list[dict]:
    """Run all 10 test questions and return results."""
    results = []

    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"\n{'━' * 60}")
        print(f"  Q{i}: {question}")
        print("━" * 60)

        result = agent.ask(question)

        # Print formatted output
        print(f"\n  SQL:\n  {result['sql']}\n")
        if result.get("retried"):
            print("  [Retry was needed — SQL was corrected after first failure]\n")
        print(f"  ANSWER:\n  {result['answer']}\n")

        if not result["success"]:
            print(f"  ERROR: {result['error']}")

        results.append({
            "question_number": i,
            "question":  result["question"],
            "sql":       result["sql"],
            "answer":    result["answer"],
            "success":   result["success"],
            "retried":   result["retried"],
            "row_count": len(result["rows"]),
            "error":     result["error"],
        })

    return results


def print_summary(results: list[dict]):
    """Print a pass/fail summary table."""
    print(f"\n{'━' * 60}")
    print("  SUMMARY")
    print("━" * 60)
    passed  = sum(1 for r in results if r["success"])
    retried = sum(1 for r in results if r["retried"])
    print(f"  Passed : {passed}/{len(results)}")
    print(f"  Retried: {retried} (SQL needed correction)")
    print()
    for r in results:
        status = "✓" if r["success"] else "✗"
        retry  = " [retried]" if r["retried"] else ""
        print(f"  {status}  Q{r['question_number']}: {r['question'][:55]}{retry}")
    print()


def save_results(results: list[dict]):
    """Save all results to a JSON log file for submission."""
    out_path = LOG_DIR / "agent_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {out_path}")


def main():
    print("\n" + "=" * 60)
    print("  STEP 5: TEXT-TO-SQL LANGCHAIN AGENT")
    print("=" * 60)

    # Initialise agent
    # gpt-4o-mini is accurate for SQL tasks and cost-efficient
    agent = TextToSQLAgent(model="claude-haiku-4-5-20251001", temperature=0.0)

    # Run all 10 questions
    results = run_all_questions(agent)

    # Summary
    print_summary(results)

    # Save to log
    save_results(results)

    print(f"  Full log saved to: {log_file}")
    print(f"  Results JSON saved to: {LOG_DIR / 'agent_results.json'}")
    print()


if __name__ == "__main__":
    main()