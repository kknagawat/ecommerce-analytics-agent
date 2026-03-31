"""
run_db.py
---------
Entry point for Step 2: Schema Design & SQLite Loading.

Run with:
    python run_db.py

What this does:
  1. Reads 4 cleaned CSVs from data/processed/
  2. Creates the SQLite schema from src/database/schema.sql
  3. Loads all data into ecommerce.db
  4. Runs post-load verification checks
"""

import logging
import sys
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "db_pipeline.log", mode="w", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

from src.database.loader   import load_all
from src.database.verifier import verify_all


def main():
    logger.info("=" * 55)
    logger.info("  STEP 2: SCHEMA DESIGN & SQLITE LOADING")
    logger.info("=" * 55)

    conn = load_all()
    passed = verify_all(conn)
    conn.close()

    if passed:
        logger.info("Step 2 complete. Database is at ecommerce.db")
        logger.info("Open it in DB Browser for SQLite to inspect visually.")
    else:
        logger.warning("Step 2 completed with verification failures.")
        logger.warning("Check logs/db_pipeline.log for details.")


if __name__ == "__main__":
    main()