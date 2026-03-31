"""
routes/health.py
----------------
GET /health — database status, row counts, agent readiness.
"""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from src.api.models import HealthResponse, TableCount
from src.api.dependencies import get_db, _agent_instance

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns database connectivity status, row counts per table, and agent readiness.",
)
def health_check(conn: sqlite3.Connection = Depends(get_db)):
    # Check DB and get row counts
    table_counts = []
    db_status = "connected"
    try:
        for table in ["customers", "products", "orders", "reviews"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            table_counts.append(TableCount(table=table, rows=count))
    except Exception as e:
        db_status = f"error: {e}"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        database=db_status,
        agent_ready=_agent_instance is not None,
        table_counts=table_counts,
        timestamp=datetime.now(timezone.utc),
    )