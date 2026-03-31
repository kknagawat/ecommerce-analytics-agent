"""
loader.py
---------
Reads the 4 cleaned CSVs from Phase 1 and loads them into SQLite.

Design decisions:
  - schema.sql is read and executed first to create tables
  - Data is inserted using parameterized queries (? placeholders) — no string concat
  - pandas NaN is converted to None before inserting (SQLite NULL)
  - numpy/pandas types are cast to plain Python types before inserting
  - Dimension tables (customers, products) are inserted before fact tables (orders, reviews)
  - PRAGMA foreign_keys = ON is set at connection time
"""

import logging
import sqlite3
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parents[2]
PROCESSED    = BASE_DIR / "data" / "processed"
SCHEMA_FILE  = Path(__file__).parent / "schema.sql"
DB_PATH      = BASE_DIR / "ecommerce.db"


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """
    Open a SQLite connection with foreign keys enabled.
    PRAGMA foreign_keys must be set per connection — it does not persist.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _nan_to_none(value):
    """
    Convert pandas NaN / numpy NaN to Python None.
    SQLite understands None as NULL. It does not understand float('nan').
    Also converts numpy integer/float types to plain Python int/float.
    """
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return int(value)      # store booleans as 0/1
    return value


def _row_to_tuple(row: pd.Series, columns: list[str]) -> tuple:
    """
    Convert a DataFrame row to a tuple of Python-native values
    in the exact column order given, with NaN → None conversion.
    """
    return tuple(_nan_to_none(row[col]) for col in columns)


# ─────────────────────────────────────────────────────────────
# SCHEMA CREATION
# ─────────────────────────────────────────────────────────────

def create_schema(conn: sqlite3.Connection) -> None:
    """
    Read schema.sql and execute it against the connection.
    IF NOT EXISTS clauses mean this is safe to run multiple times.
    """
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    logger.info("Schema created from schema.sql")


# ─────────────────────────────────────────────────────────────
# TABLE LOADERS
# ─────────────────────────────────────────────────────────────

def load_customers(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert all rows from the cleaned customers DataFrame."""
    columns = [
        "customer_id", "first_name", "last_name", "email", "has_email",
        "phone", "city", "country", "postal_code", "signup_date",
        "is_active", "loyalty_tier"
    ]

    # Convert is_active bool → int (True→1, False→0)
    df = df.copy()
    df["is_active"]  = df["is_active"].map(lambda x: 1 if x is True or x == True else 0)
    df["has_email"]  = df["has_email"].map(lambda x: 1 if x is True or x == True else 0)

    sql = f"""
        INSERT OR IGNORE INTO customers ({', '.join(columns)})
        VALUES ({', '.join(['?'] * len(columns))})
    """

    rows = [_row_to_tuple(row, columns) for _, row in df.iterrows()]
    conn.executemany(sql, rows)
    conn.commit()
    logger.info(f"Loaded {len(rows)} rows into customers")


def load_products(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert all rows from the cleaned products DataFrame."""
    columns = [
        "product_id", "sku", "product_name", "category",
        "unit_price", "stock_quantity", "weight_kg", "created_date"
    ]

    df = df.copy()
    # Clamp negative stock_quantity to 0 — schema enforces >= 0
    # Phase 1 cleaner missed this edge case; fixed here with logging
    neg_stock = (df["stock_quantity"] < 0).sum()
    if neg_stock:
        logger.warning(f"[products] Clamping {neg_stock} negative stock_quantity values to 0")
        df["stock_quantity"] = df["stock_quantity"].clip(lower=0)

    sql = f"""
        INSERT OR IGNORE INTO products ({', '.join(columns)})
        VALUES ({', '.join(['?'] * len(columns))})
    """

    rows = [_row_to_tuple(row, columns) for _, row in df.iterrows()]
    conn.executemany(sql, rows)
    conn.commit()
    logger.info(f"Loaded {len(rows)} rows into products")


def load_orders(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert all rows from the cleaned orders DataFrame."""
    columns = [
        "order_id", "customer_id", "product_id", "quantity",
        "unit_price", "total_amount", "order_date", "status",
        "payment_method", "shipping_address_city", "discount_pct"
    ]

    sql = f"""
        INSERT OR IGNORE INTO orders ({', '.join(columns)})
        VALUES ({', '.join(['?'] * len(columns))})
    """

    rows = [_row_to_tuple(row, columns) for _, row in df.iterrows()]
    conn.executemany(sql, rows)
    conn.commit()
    logger.info(f"Loaded {len(rows)} rows into orders")


def load_reviews(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert all rows from the cleaned reviews DataFrame."""
    columns = [
        "review_id", "product_id", "customer_id", "rating",
        "review_text", "has_review_text", "review_date",
        "verified_purchase", "helpful_votes"
    ]

    df = df.copy()
    # Convert booleans to int
    df["verified_purchase"] = df["verified_purchase"].map(
        lambda x: 1 if x is True or x == True else (0 if x is False or x == False else None)
    )
    df["has_review_text"] = df["has_review_text"].map(
        lambda x: 1 if x is True or x == True else 0
    )

    sql = f"""
        INSERT OR IGNORE INTO reviews ({', '.join(columns)})
        VALUES ({', '.join(['?'] * len(columns))})
    """

    rows = [_row_to_tuple(row, columns) for _, row in df.iterrows()]
    conn.executemany(sql, rows)
    conn.commit()
    logger.info(f"Loaded {len(rows)} rows into reviews")


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def load_all() -> sqlite3.Connection:
    """
    Full loading pipeline:
      1. Read 4 clean CSVs
      2. Create schema
      3. Insert dimension tables first (customers, products)
      4. Insert fact tables second (orders, reviews)
    Returns the open connection for use by verifier.
    """
    logger.info("=" * 55)
    logger.info("  STEP 2: LOADING DATA INTO SQLITE")
    logger.info("=" * 55)

    # ── Read cleaned CSVs ──────────────────────────────────
    logger.info("\n── Reading cleaned CSVs ──")
    customers = pd.read_csv(PROCESSED / "customers_clean.csv")
    products  = pd.read_csv(PROCESSED / "products_clean.csv")
    orders    = pd.read_csv(PROCESSED / "orders_clean.csv")
    reviews   = pd.read_csv(PROCESSED / "reviews_clean.csv")

    logger.info(f"customers : {len(customers)} rows")
    logger.info(f"products  : {len(products)} rows")
    logger.info(f"orders    : {len(orders)} rows")
    logger.info(f"reviews   : {len(reviews)} rows")

    # ── Connect and create schema ──────────────────────────
    logger.info("\n── Creating schema ──")
    conn = _get_connection()
    create_schema(conn)

    # ── Insert in correct order ────────────────────────────
    # Dimension tables first — fact tables reference them
    logger.info("\n── Inserting data ──")
    load_customers(conn, customers)
    load_products(conn, products)
    load_orders(conn, orders)
    load_reviews(conn, reviews)

    logger.info("\nAll data loaded successfully.")
    return conn


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
    load_all()
