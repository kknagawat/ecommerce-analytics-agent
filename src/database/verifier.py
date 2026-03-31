"""
verifier.py
-----------
Post-load integrity checks for the SQLite database.

Checks:
  1. Row counts match cleaned CSVs exactly
  2. No orphaned foreign keys (orders → customers, orders → products, reviews → products)
  3. No constraint violations (price > 0, quantity > 0, rating 1-5)
  4. Primary keys are unique and not null
"""

import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"


def _query(conn: sqlite3.Connection, sql: str) -> list:
    """Run a SQL query and return all rows."""
    return conn.execute(sql).fetchall()


def _count(conn: sqlite3.Connection, table: str) -> int:
    """Return row count for a table."""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ─────────────────────────────────────────────────────────────
# CHECK 1 — Row counts
# ─────────────────────────────────────────────────────────────

def check_row_counts(conn: sqlite3.Connection) -> bool:
    """
    Compare row counts in SQLite against the cleaned CSV files.
    They must match exactly.
    """
    logger.info("\n── CHECK 1: Row counts ──")
    all_pass = True

    expected = {
        "customers": len(pd.read_csv(PROCESSED / "customers_clean.csv")),
        "products":  len(pd.read_csv(PROCESSED / "products_clean.csv")),
        "orders":    len(pd.read_csv(PROCESSED / "orders_clean.csv")),
        "reviews":   len(pd.read_csv(PROCESSED / "reviews_clean.csv")),
    }

    for table, exp in expected.items():
        actual = _count(conn, table)
        if actual == exp:
            logger.info(f"  ✓ PASS  {table}: {actual} rows")
        else:
            logger.warning(f"  ✗ FAIL  {table}: expected {exp}, got {actual}")
            all_pass = False

    return all_pass


# ─────────────────────────────────────────────────────────────
# CHECK 2 — Foreign key integrity
# ─────────────────────────────────────────────────────────────

def check_foreign_keys(conn: sqlite3.Connection) -> bool:
    """
    Check for orphaned foreign key references.
    Every customer_id in orders must exist in customers.
    Every product_id in orders and reviews must exist in products.
    """
    logger.info("\n── CHECK 2: Foreign key integrity ──")
    all_pass = True

    checks = [
        (
            "orders.customer_id → customers",
            """
            SELECT COUNT(*) FROM orders
            WHERE customer_id NOT IN (SELECT customer_id FROM customers)
            """
        ),
        (
            "orders.product_id → products",
            """
            SELECT COUNT(*) FROM orders
            WHERE product_id NOT IN (SELECT product_id FROM products)
            """
        ),
        (
            "reviews.product_id → products",
            """
            SELECT COUNT(*) FROM reviews
            WHERE product_id NOT IN (SELECT product_id FROM products)
            """
        ),
    ]

    for label, sql in checks:
        count = conn.execute(sql).fetchone()[0]
        if count == 0:
            logger.info(f"  ✓ PASS  {label}: 0 orphans")
        else:
            logger.warning(f"  ✗ FAIL  {label}: {count} orphaned rows")
            all_pass = False

    return all_pass


# ─────────────────────────────────────────────────────────────
# CHECK 3 — Constraint violations
# ─────────────────────────────────────────────────────────────

def check_constraints(conn: sqlite3.Connection) -> bool:
    """
    Check that no rows violate the business rules defined in schema.sql.
    """
    logger.info("\n── CHECK 3: Constraint violations ──")
    all_pass = True

    checks = [
        ("products: unit_price > 0",
         "SELECT COUNT(*) FROM products WHERE unit_price <= 0"),

        ("orders: unit_price > 0",
         "SELECT COUNT(*) FROM orders WHERE unit_price <= 0"),

        ("orders: quantity > 0",
         "SELECT COUNT(*) FROM orders WHERE quantity <= 0"),

        ("orders: discount_pct >= 0",
         "SELECT COUNT(*) FROM orders WHERE discount_pct < 0"),

        ("reviews: rating between 1 and 5",
         "SELECT COUNT(*) FROM reviews WHERE rating IS NOT NULL AND (rating < 1 OR rating > 5)"),

        ("reviews: helpful_votes >= 0",
         "SELECT COUNT(*) FROM reviews WHERE helpful_votes < 0"),

        ("customers: loyalty_tier valid",
         "SELECT COUNT(*) FROM customers WHERE loyalty_tier NOT IN ('platinum','gold','silver','bronze','none')"),
    ]

    for label, sql in checks:
        count = conn.execute(sql).fetchone()[0]
        if count == 0:
            logger.info(f"  ✓ PASS  {label}")
        else:
            logger.warning(f"  ✗ FAIL  {label}: {count} violations")
            all_pass = False

    return all_pass


# ─────────────────────────────────────────────────────────────
# CHECK 4 — Primary key uniqueness
# ─────────────────────────────────────────────────────────────

def check_primary_keys(conn: sqlite3.Connection) -> bool:
    """
    Confirm primary keys are unique and non-null in every table.
    """
    logger.info("\n── CHECK 4: Primary key uniqueness ──")
    all_pass = True

    tables = {
        "customers": "customer_id",
        "products":  "product_id",
        "orders":    "order_id",
        "reviews":   "review_id",
    }

    for table, pk in tables.items():
        total  = _count(conn, table)
        unique = conn.execute(
            f"SELECT COUNT(DISTINCT {pk}) FROM {table}"
        ).fetchone()[0]

        if total == unique:
            logger.info(f"  ✓ PASS  {table}.{pk}: {unique} unique values")
        else:
            logger.warning(f"  ✗ FAIL  {table}.{pk}: {total} rows but only {unique} unique")
            all_pass = False

    return all_pass


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def verify_all(conn: sqlite3.Connection) -> bool:
    """
    Run all 4 verification checks.
    Returns True if everything passes, False if any check fails.
    """
    logger.info("\n" + "=" * 55)
    logger.info("  POST-LOAD VERIFICATION")
    logger.info("=" * 55)

    results = [
        check_row_counts(conn),
        check_foreign_keys(conn),
        check_constraints(conn),
        check_primary_keys(conn),
    ]

    all_pass = all(results)

    logger.info("\n" + "=" * 55)
    if all_pass:
        logger.info("  ✓ ALL CHECKS PASSED — database is clean and consistent")
    else:
        logger.warning("  ✗ SOME CHECKS FAILED — review warnings above")
    logger.info("=" * 55 + "\n")

    return all_pass


if __name__ == "__main__":
    import sqlite3
    from pathlib import Path
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
    db_path = Path(__file__).resolve().parents[2] / "ecommerce.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    verify_all(conn)
    conn.close()
