"""
routes/query.py
---------------
POST /query          — natural language → SQL → answer
GET  /query/history  — paginated log of past queries
POST /query/validate — check if a SQL string is safe (no execution)
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from src.api.models import (
    QueryRequest, QueryResponse,
    QueryHistoryItem, QueryHistoryResponse,
    ValidateRequest, ValidateResponse,
)
from src.api.dependencies import get_db, get_agent
from src.agent.agent import _is_safe_sql

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory query history ────────────────────────────────
# Stores the last 1000 queries. A production system would
# persist these to a SQLite table.
_query_history: list[dict] = []
_query_counter: int = 0


def _add_to_history(entry: dict):
    """Append to history, keeping max 1000 entries."""
    global _query_counter, _query_history
    _query_counter += 1
    entry["id"] = _query_counter
    _query_history.append(entry)
    if len(_query_history) > 1000:
        _query_history = _query_history[-1000:]


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Natural language query",
    description="Send a natural language question. The agent generates SQL, executes it, and returns a plain-English answer.",
    responses={
        400: {"description": "Empty or invalid question"},
        500: {"description": "Agent or database error"},
        503: {"description": "Agent not initialised"},
    },
)
def natural_language_query(
    request: QueryRequest,
    agent=Depends(get_agent),
):
    start_ms = time.time() * 1000

    try:
        result = agent.ask(request.question)
    except Exception as e:
        logger.error(f"Agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    execution_time_ms = round(time.time() * 1000 - start_ms, 2)

    if not result["success"] and result.get("error"):
        # Agent ran but failed — return 500 with details
        raise HTTPException(
            status_code=500,
            detail=result["error"],
        )

    response = QueryResponse(
        question=result["question"],
        answer=result["answer"],
        sql_generated=result["sql"],
        raw_result=result["rows"],
        execution_time_ms=execution_time_ms,
        retried=result["retried"],
        row_count=len(result["rows"]),
    )

    # Save to history
    _add_to_history({
        "question":          request.question,
        "sql_generated":     result["sql"],
        "answer":            result["answer"],
        "execution_time_ms": execution_time_ms,
        "success":           result["success"],
        "retried":           result["retried"],
        "row_count":         len(result["rows"]),
        "timestamp":         datetime.now(timezone.utc),
    })

    return response


@router.get(
    "/query/history",
    response_model=QueryHistoryResponse,
    summary="Query history",
    description="Returns past queries with their generated SQL, answers, and timestamps. Paginated with limit/offset.",
)
def query_history(
    limit:  int = 10,
    offset: int = 0,
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    total = len(_query_history)
    # Most recent first
    items_raw = list(reversed(_query_history))[offset: offset + limit]

    items = [
        QueryHistoryItem(
            id=item["id"],
            question=item["question"],
            sql_generated=item["sql_generated"],
            answer=item["answer"],
            execution_time_ms=item["execution_time_ms"],
            success=item["success"],
            retried=item["retried"],
            row_count=item["row_count"],
            timestamp=item["timestamp"],
        )
        for item in items_raw
    ]

    return QueryHistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/query/validate",
    response_model=ValidateResponse,
    summary="Validate SQL safety",
    description="Check if a SQL query is safe to execute (SELECT-only). Does NOT execute the query.",
)
def validate_sql(request: ValidateRequest):
    safe, reason = _is_safe_sql(request.sql)
    return ValidateResponse(
        sql=request.sql,
        is_safe=safe,
        reason=reason if not safe else "Query is a safe SELECT statement",
    )