"""
run_pipeline.py
---------------
Main entry point for Step 1: Data Ingestion, Cleaning & Exploration.

Run with:
    python run_pipeline.py

What this does:
  1. Loads all four raw files
  2. Profiles raw data (saves reports to data/processed/)
  3. Runs the cleaning pipeline
  4. Profiles cleaned data
  5. Runs post-clean validation assertions
  6. Saves cleaned CSVs to data/processed/
"""

import logging
import sys
from pathlib import Path

import pandas as pd

# ── Setup logging ──────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Import pipeline modules ────────────────────────────────
from src.ingestion.loader import load_all
from src.ingestion.profiler import profile_all
from src.ingestion.cleaner import clean_all
from src.ingestion.validator import validate_all

PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def save_cleaned(cleaned: dict[str, pd.DataFrame]):
    """Save each cleaned DataFrame as a CSV to data/processed/."""
    for name, df in cleaned.items():
        out_path = PROCESSED_DIR / f"{name}_clean.csv"
        df.to_csv(out_path, index=False)
        logger.info(f"Saved {name}_clean.csv → {df.shape[0]} rows, {df.shape[1]} columns")


def main():
    logger.info("=" * 60)
    logger.info("  STEP 1: DATA INGESTION, CLEANING & EXPLORATION")
    logger.info("=" * 60)

    # ── PHASE 1: Load raw files ────────────────────────────
    logger.info("\n── LOADING RAW FILES ──────────────────────────────────")
    raw = load_all()

    # ── PHASE 2: Profile raw data ──────────────────────────
    logger.info("\n── PROFILING RAW DATA ─────────────────────────────────")
    raw_labeled = {f"{k}_raw": v for k, v in raw.items()}
    profile_all(raw_labeled, save=True)

    # ── PHASE 3: Clean ─────────────────────────────────────
    logger.info("\n── RUNNING CLEANING PIPELINE ──────────────────────────")
    cleaned = clean_all(raw)

    # ── PHASE 4: Profile cleaned data ─────────────────────
    logger.info("\n── PROFILING CLEANED DATA ─────────────────────────────")
    cleaned_labeled = {f"{k}_clean": v for k, v in cleaned.items()}
    profile_all(cleaned_labeled, save=True)

    # ── PHASE 5: Validate ──────────────────────────────────
    logger.info("\n── RUNNING VALIDATION ─────────────────────────────────")
    results = validate_all(cleaned)

    # ── PHASE 6: Save cleaned CSVs ─────────────────────────
    logger.info("\n── SAVING CLEANED FILES ───────────────────────────────")
    save_cleaned(cleaned)

    # ── Final row count summary ────────────────────────────
    logger.info("\n── ROW COUNT SUMMARY ──────────────────────────────────")
    for name, df_raw in raw.items():
        df_clean = cleaned[name]
        dropped = len(df_raw) - len(df_clean)
        logger.info(
            f"  {name:<12} raw={len(df_raw):>5}  clean={len(df_clean):>5}  dropped={dropped:>4}"
        )

    logger.info("\n  Pipeline complete. Check data/processed/ for output files.")
    logger.info("  Check logs/pipeline.log for full execution log.\n")

    return cleaned


if __name__ == "__main__":
    main()
