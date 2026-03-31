"""
routes/etl.py
-------------
POST /etl/run    — triggers full ETL pipeline in background, returns job_id
GET  /etl/status/{job_id} — poll job status
"""

import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.api.models import ETLJobResponse, ETLRequest, ETLStatusResponse
from src.api.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

DB_PATH  = Path(__file__).resolve().parents[3] / "ecommerce.db"

# In-memory job store — maps job_id → status dict.
# A production system would use Redis or a jobs table in SQLite.
_jobs: dict[str, dict] = {}


def _run_etl_pipeline(job_id: str, force_reload: bool):
    """
    The actual ETL work — runs in a background task.
    Updates _jobs[job_id] as it progresses.
    """
    _jobs[job_id]["status"] = "running"
    start = time.time()
    errors = []

    try:
        from src.ingestion.loader  import load_all as load_raw
        from src.ingestion.cleaner import clean_all
        from src.database.loader   import load_all as load_db, create_schema, _get_connection

        # ── Step 1: Load and clean raw data ──────────────
        logger.info(f"[{job_id}] Loading raw data...")
        raw     = load_raw()
        cleaned = clean_all(raw)

        # ── Step 2: Load into SQLite ──────────────────────
        logger.info(f"[{job_id}] Loading into database...")

        if force_reload and DB_PATH.exists():
            DB_PATH.unlink()
            logger.info(f"[{job_id}] Deleted existing database for force reload")

        conn = _get_connection()
        create_schema(conn)

        from src.database.loader import (
            load_customers, load_products, load_orders, load_reviews
        )
        load_customers(conn, cleaned["customers"])
        load_products(conn, cleaned["products"])
        load_orders(conn, cleaned["orders"])
        load_reviews(conn, cleaned["reviews"])
        conn.close()

        # ── Step 3: Gather row counts ─────────────────────
        rows_loaded = {name: len(df) for name, df in cleaned.items()}

        _jobs[job_id].update({
            "status":       "completed",
            "completed_at": datetime.now(timezone.utc),
            "duration_sec": round(time.time() - start, 2),
            "rows_loaded":  rows_loaded,
            "errors":       errors,
            "message":      "Pipeline completed successfully",
        })
        logger.info(f"[{job_id}] ETL completed in {_jobs[job_id]['duration_sec']}s")

    except Exception as e:
        logger.error(f"[{job_id}] ETL failed: {e}")
        _jobs[job_id].update({
            "status":       "failed",
            "completed_at": datetime.now(timezone.utc),
            "duration_sec": round(time.time() - start, 2),
            "errors":       [str(e)],
            "message":      f"Pipeline failed: {e}",
        })


@router.post(
    "/etl/run",
    response_model=ETLJobResponse,
    status_code=202,
    summary="Trigger ETL pipeline",
    description="Runs ingest → clean → load in the background. Returns a job_id to poll status.",
)
def run_etl(
    request: ETLRequest = ETLRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    job_id = f"etl_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(timezone.utc)

    _jobs[job_id] = {
        "job_id":       job_id,
        "status":       "queued",
        "started_at":   started_at,
        "completed_at": None,
        "duration_sec": None,
        "rows_loaded":  None,
        "errors":       [],
        "message":      "Job queued, starting soon",
    }

    background_tasks.add_task(_run_etl_pipeline, job_id, request.force_reload)
    logger.info(f"ETL job {job_id} queued")

    return ETLJobResponse(
        job_id=job_id,
        status="queued",
        message="ETL pipeline started in background. Poll /etl/status/{job_id} for updates.",
        started_at=started_at,
    )


@router.get(
    "/etl/status/{job_id}",
    response_model=ETLStatusResponse,
    summary="Poll ETL job status",
    description="Returns current status of a background ETL job.",
)
def etl_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    j = _jobs[job_id]
    return ETLStatusResponse(
        job_id=j["job_id"],
        status=j["status"],
        started_at=j["started_at"],
        completed_at=j.get("completed_at"),
        duration_sec=j.get("duration_sec"),
        rows_loaded=j.get("rows_loaded"),
        errors=j.get("errors", []),
        message=j.get("message", ""),
    )