"""
routes/analytics.py
-------------------
GET /analytics/summary — pre-computed analytics via direct SQL.
Does NOT use the agent — direct SQLite queries for speed and reliability.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from src.api.models import (
    AnalyticsSummaryResponse,
    TopProduct,
    TopCustomer,
    OrderStatusDist,
)
from src.api.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Analytics summary",
    description="Returns pre-computed analytics: revenue, order counts, top products, top customers, status distribution.",
)
def analytics_summary(conn: sqlite3.Connection = Depends(get_db)):

    # ── Total revenue ──────────────────────────────────────
    total_revenue = conn.execute(
        "SELECT ROUND(SUM(total_amount), 2) FROM orders WHERE total_amount IS NOT NULL"
    ).fetchone()[0] or 0.0

    # ── Total orders ───────────────────────────────────────
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    # ── Total customers ────────────────────────────────────
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]

    # ── Total products ─────────────────────────────────────
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # ── Average order value ────────────────────────────────
    avg_order_value = conn.execute(
        "SELECT ROUND(AVG(total_amount), 2) FROM orders WHERE total_amount IS NOT NULL"
    ).fetchone()[0] or 0.0

    # ── Top 5 products by revenue ──────────────────────────
    top_products_rows = conn.execute("""
        SELECT
            p.product_id,
            p.product_name,
            p.category,
            ROUND(SUM(o.total_amount), 2) AS total_revenue,
            SUM(o.quantity)               AS units_sold
        FROM orders   o
        JOIN products p ON o.product_id = p.product_id
        WHERE o.total_amount IS NOT NULL
        GROUP BY p.product_id, p.product_name, p.category
        ORDER BY total_revenue DESC
        LIMIT 5
    """).fetchall()

    top_5_products = [
        TopProduct(
            product_id=r["product_id"],
            product_name=r["product_name"],
            category=r["category"],
            total_revenue=r["total_revenue"],
            units_sold=r["units_sold"],
        )
        for r in top_products_rows
    ]

    # ── Top 5 customers by spend ───────────────────────────
    top_customers_rows = conn.execute("""
        SELECT
            o.customer_id,
            c.first_name || ' ' || c.last_name AS customer_name,
            COUNT(o.order_id)                  AS total_orders,
            ROUND(SUM(o.total_amount), 2)       AS total_spent
        FROM orders    o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.total_amount IS NOT NULL
        GROUP BY o.customer_id
        ORDER BY total_spent DESC
        LIMIT 5
    """).fetchall()

    top_5_customers = [
        TopCustomer(
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            total_orders=r["total_orders"],
            total_spent=r["total_spent"],
        )
        for r in top_customers_rows
    ]

    # ── Order status distribution ──────────────────────────
    status_rows = conn.execute("""
        SELECT
            status,
            COUNT(*) AS count
        FROM orders
        GROUP BY status
        ORDER BY count DESC
    """).fetchall()

    status_dist = [
        OrderStatusDist(
            status=r["status"],
            count=r["count"],
            pct=round(r["count"] / total_orders * 100, 2) if total_orders else 0.0,
        )
        for r in status_rows
    ]

    return AnalyticsSummaryResponse(
        total_revenue=total_revenue,
        total_orders=total_orders,
        total_customers=total_customers,
        total_products=total_products,
        avg_order_value=avg_order_value,
        top_5_products=top_5_products,
        top_5_customers=top_5_customers,
        order_status_dist=status_dist,
        computed_at=datetime.now(timezone.utc),
    )