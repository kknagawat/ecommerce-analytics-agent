"""
loader.py
---------
Responsible for loading raw data files into pandas DataFrames.
No cleaning happens here — this module is intentionally dumb.
It just reads files and returns raw DataFrames exactly as-is.
"""

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def load_orders() -> pd.DataFrame:
    """
    Load orders_raw.csv into a DataFrame.
    Returns raw data with no transformations.
    """
    path = RAW_DIR / "orders_raw.csv"
    df = pd.read_csv(path, dtype=str)  # dtype=str preserves messy values like "AED 58.37"
    logger.info(f"Loaded orders: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def load_customers() -> pd.DataFrame:
    """
    Load customers_raw.json into a flat DataFrame.
    The JSON is a list of objects with nested 'name' and 'address' fields.
    pd.json_normalize flattens these into name.first, address.city etc.
    """
    path = RAW_DIR / "customers_raw.json"
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # json_normalize flattens nested dicts using '.' separator by default
    df = pd.json_normalize(raw)
    logger.info(f"Loaded customers: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def load_products() -> pd.DataFrame:
    """
    Load products_raw.csv into a DataFrame.
    """
    path = RAW_DIR / "products_raw.csv"
    df = pd.read_csv(path, dtype=str)
    logger.info(f"Loaded products: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def load_reviews() -> pd.DataFrame:
    """
    Load reviews_raw.csv into a DataFrame.
    """
    path = RAW_DIR / "reviews_raw.csv"
    df = pd.read_csv(path, dtype=str)
    logger.info(f"Loaded reviews: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def load_all() -> dict[str, pd.DataFrame]:
    """
    Convenience function — load all four files at once.
    Returns a dict keyed by name.
    """
    return {
        "orders": load_orders(),
        "customers": load_customers(),
        "products": load_products(),
        "reviews": load_reviews(),
    }
