"""
profiler.py
-----------
Generates a data quality summary report for any DataFrame.
Run this BEFORE cleaning to document what the raw data looks like,
and AFTER cleaning to confirm issues were resolved.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def profile(df: pd.DataFrame, name: str, save: bool = True) -> dict:
    """
    Profile a DataFrame and return a summary dict.

    Covers:
    - Row and column counts
    - Per-column: dtype, null count, null %, unique count
    - Duplicate row count
    - Unique value counts for low-cardinality columns (<=20 unique values)

    Parameters
    ----------
    df   : The DataFrame to profile
    name : Label used in output (e.g. "orders_raw", "customers_clean")
    save : If True, writes the report to data/processed/<name>_profile.txt
    """
    lines = []

    def log(line=""):
        lines.append(line)

    log(f"{'=' * 60}")
    log(f"  PROFILE REPORT: {name.upper()}")
    log(f"{'=' * 60}")
    log(f"  Rows      : {df.shape[0]:,}")
    log(f"  Columns   : {df.shape[1]}")
    log(f"  Duplicates: {df.duplicated().sum()} exact duplicate rows")
    log()

    # Per-column summary
    log(f"  {'Column':<30} {'Dtype':<15} {'Nulls':>6} {'Null%':>7} {'Unique':>8}")
    log(f"  {'-' * 70}")

    col_stats = {}
    for col in df.columns:
        null_count = int(df[col].isna().sum())
        null_pct = null_count / len(df) * 100
        unique_count = int(df[col].nunique(dropna=False))
        dtype = str(df[col].dtype)
        log(f"  {col:<30} {dtype:<15} {null_count:>6} {null_pct:>6.1f}% {unique_count:>8}")
        col_stats[col] = {
            "dtype": dtype,
            "nulls": null_count,
            "null_pct": round(null_pct, 2),
            "unique": unique_count,
        }

    log()

    # Unique value breakdown for categorical / low-cardinality columns
    log("  CATEGORICAL COLUMN VALUE COUNTS")
    log(f"  {'-' * 60}")
    for col in df.columns:
        n_unique = df[col].nunique(dropna=False)
        if n_unique <= 20 and df[col].dtype == object:
            log(f"\n  [{col}]")
            counts = df[col].value_counts(dropna=False)
            for val, cnt in counts.items():
                log(f"    {str(val):<30} {cnt:>5} ({cnt/len(df)*100:.1f}%)")

    log()
    log(f"{'=' * 60}")

    report_text = "\n".join(lines)
    print(report_text)

    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORTS_DIR / f"{name}_profile.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        logger.info(f"Profile saved to {out_path}")

    return {
        "name": name,
        "rows": df.shape[0],
        "columns": df.shape[1],
        "duplicates": int(df.duplicated().sum()),
        "column_stats": col_stats,
    }


def profile_all(dataframes: dict[str, pd.DataFrame], save: bool = True) -> dict:
    """
    Profile multiple DataFrames at once.
    Accepts the dict returned by loader.load_all().
    """
    return {name: profile(df, name, save=save) for name, df in dataframes.items()}
