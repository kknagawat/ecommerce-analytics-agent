"""
analytics.py
------------
Step 3 — Pandas Analytics & DataFrame Operations

Five analyses:
  1. Revenue Analysis         — category × month pivot table
  2. Customer Segmentation    — RFM-style segments (Active / At Risk / Churned)
  3. Product Performance      — units sold, revenue, avg rating, rank per category
  4. Discount Impact Analysis — AOV, completion rate, return rate by discount tier
  5. Data Quality Report      — summary of all fixes applied in Step 1

Run with:
    python analytics.py

All results are printed and saved to data/processed/
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent
PROCESSED = BASE_DIR / "data" / "processed"
REPORTS   = BASE_DIR / "data" / "processed"


# ─────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────

def load_data() -> dict[str, pd.DataFrame]:
    """Load all 4 cleaned CSVs and parse date columns."""
    orders    = pd.read_csv(PROCESSED / "orders_clean.csv",    parse_dates=["order_date"])
    products  = pd.read_csv(PROCESSED / "products_clean.csv",  parse_dates=["created_date"])
    customers = pd.read_csv(PROCESSED / "customers_clean.csv", parse_dates=["signup_date"])
    reviews   = pd.read_csv(PROCESSED / "reviews_clean.csv",   parse_dates=["review_date"])

    logger.info(f"Loaded: orders={len(orders)}, products={len(products)}, "
                f"customers={len(customers)}, reviews={len(reviews)}")
    return {
        "orders": orders, "products": products,
        "customers": customers, "reviews": reviews,
    }


# ─────────────────────────────────────────────────────────────
# ANALYSIS 1 — Revenue by Category and Month
# ─────────────────────────────────────────────────────────────

def analysis_revenue(orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """
    Compute total revenue by product category and month.
    Returns a pivot table: rows=month, columns=category, values=revenue.

    Steps:
      1. Merge orders with products to get category per order
      2. Extract year-month from order_date
      3. groupby category + month to get revenue
      4. pivot_table to create the matrix
    """
    print("\n" + "=" * 60)
    print("  ANALYSIS 1 — Revenue by Category and Month")
    print("=" * 60)

    # ── Step 1: Merge orders with products on product_id ──
    # We only need category from products — select early to keep it lean
    merged = pd.merge(
        orders[["order_id", "product_id", "total_amount", "order_date"]],
        products[["product_id", "category"]],
        on="product_id",
        how="left",       # keep all orders even if product somehow missing
    )

    # ── Step 2: Extract year-month as a Period for clean sorting ──
    # Period('2024-03', 'M') sorts correctly and displays as "2024-03"
    merged["year_month"] = merged["order_date"].dt.to_period("M")

    # ── Step 3: Drop rows where total_amount is null (25 rows) ──
    # Can't include in revenue without a value
    merged = merged.dropna(subset=["total_amount"])

    # ── Step 4: Group by category and month ──
    revenue_by_cat_month = (
        merged
        .groupby(["year_month", "category"])["total_amount"]
        .sum()
        .reset_index()
        .rename(columns={"total_amount": "revenue"})
    )

    # ── Step 5: Pivot — rows=month, columns=category ──
    pivot = revenue_by_cat_month.pivot_table(
        index="year_month",
        columns="category",
        values="revenue",
        aggfunc="sum",       # sum in case of any duplicate group keys
        fill_value=0,        # months with no sales in a category → 0
    )

    # ── Step 6: Add a row total column ──
    pivot["TOTAL"] = pivot.sum(axis=1)

    # ── Step 7: Sort by month ──
    pivot = pivot.sort_index()

    # ── Print ──────────────────────────────────────────────
    print(f"\nShape: {pivot.shape[0]} months × {pivot.shape[1]} categories")
    print("\nMonth-over-month revenue by category (£):\n")
    print(pivot.to_string())

    # ── Month-over-month growth on total ──────────────────
    pivot["mom_growth_pct"] = pivot["TOTAL"].pct_change() * 100

    print("\nMonth-over-month total revenue growth:\n")
    print(pivot[["TOTAL", "mom_growth_pct"]].round(2).to_string())

    # Save
    out = REPORTS / "analysis1_revenue_pivot.csv"
    pivot.to_csv(out)
    logger.info(f"Saved → {out}")

    return pivot


# ─────────────────────────────────────────────────────────────
# ANALYSIS 2 — Customer Segmentation
# ─────────────────────────────────────────────────────────────

def analysis_customer_segmentation(
    orders: pd.DataFrame,
    customers: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build a customer-level summary and segment into:
      Active  — ordered within last 90 days
      At Risk — ordered 91–180 days ago
      Churned — no order for > 180 days

    Uses vectorized operations — no iterrows, no loops.
    """
    print("\n" + "=" * 60)
    print("  ANALYSIS 2 — Customer Segmentation")
    print("=" * 60)

    # ── Reference date: most recent order date in the dataset ──
    # Using max order date rather than today() so results are
    # reproducible regardless of when the script is run
    reference_date = orders["order_date"].max()
    print(f"\nReference date (most recent order): {reference_date.date()}")

    # ── Build customer-level summary from orders ───────────
    customer_summary = (
        orders
        .groupby("customer_id")
        .agg(
            total_orders    = ("order_id",     "count"),
            total_spent     = ("total_amount", "sum"),
            first_order_date= ("order_date",   "min"),
            last_order_date = ("order_date",   "max"),
        )
        .reset_index()
    )

    # ── avg_order_value — vectorized division ──────────────
    # Guard against division by zero (total_orders should always be > 0 here)
    customer_summary["avg_order_value"] = (
        customer_summary["total_spent"] / customer_summary["total_orders"]
    ).round(2)

    # ── days_since_last_order — vectorized timedelta ───────
    customer_summary["days_since_last_order"] = (
        reference_date - customer_summary["last_order_date"]
    ).dt.days

    # ── Segmentation using pd.cut — vectorized, no loops ──
    # pd.cut assigns a label based on which bin the value falls into
    bins   = [-1, 90, 180, float("inf")]
    labels = ["Active", "At Risk", "Churned"]
    customer_summary["segment"] = pd.cut(
        customer_summary["days_since_last_order"],
        bins=bins,
        labels=labels,
        right=True,         # bins are (left, right] — right-inclusive
    )

    # ── Merge with customer profile info ──────────────────
    customer_summary = pd.merge(
        customer_summary,
        customers[["customer_id", "first_name", "last_name",
                   "city", "loyalty_tier", "is_active"]],
        on="customer_id",
        how="left",
    )

    # ── Print segment distribution ─────────────────────────
    print("\nCustomer segment distribution:\n")
    segment_counts = customer_summary["segment"].value_counts()
    print(segment_counts.to_string())

    print("\nSegment revenue summary:\n")
    segment_revenue = (
        customer_summary
        .groupby("segment", observed=True)
        .agg(
            customers        = ("customer_id",     "count"),
            total_revenue    = ("total_spent",     "sum"),
            avg_spend        = ("total_spent",     "mean"),
            avg_orders       = ("total_orders",    "mean"),
        )
        .round(2)
    )
    print(segment_revenue.to_string())

    print("\nSample — top 10 customers by total spent:\n")
    top10 = (
        customer_summary
        .nlargest(10, "total_spent")
        [["customer_id", "first_name", "last_name", "total_orders",
          "total_spent", "avg_order_value", "days_since_last_order", "segment"]]
    )
    print(top10.to_string(index=False))

    # Save
    out = REPORTS / "analysis2_customer_segments.csv"
    customer_summary.to_csv(out, index=False)
    logger.info(f"Saved → {out}")

    return customer_summary


# ─────────────────────────────────────────────────────────────
# ANALYSIS 3 — Product Performance
# ─────────────────────────────────────────────────────────────

def analysis_product_performance(
    orders: pd.DataFrame,
    products: pd.DataFrame,
    reviews: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge orders + products + reviews to compute per-product:
      units_sold, total_revenue, avg_rating, review_count
    Then rank products within each category.
    """
    print("\n" + "=" * 60)
    print("  ANALYSIS 3 — Product Performance")
    print("=" * 60)

    # ── Step 1: Order-level aggregation per product ────────
    order_stats = (
        orders
        .groupby("product_id")
        .agg(
            units_sold    = ("quantity",     "sum"),
            total_revenue = ("total_amount", "sum"),
            order_count   = ("order_id",     "count"),
        )
        .reset_index()
    )

    # ── Step 2: Review-level aggregation per product ───────
    review_stats = (
        reviews
        .groupby("product_id")
        .agg(
            avg_rating    = ("rating",     "mean"),
            review_count  = ("review_id",  "count"),
        )
        .reset_index()
    )
    review_stats["avg_rating"] = review_stats["avg_rating"].round(2)

    # ── Step 3: Merge everything ───────────────────────────
    # Left join from products so every product appears even without orders
    product_perf = pd.merge(
        products[["product_id", "product_name", "category", "unit_price"]],
        order_stats,
        on="product_id",
        how="left",
    )
    product_perf = pd.merge(
        product_perf,
        review_stats,
        on="product_id",
        how="left",
    )

    # ── Step 4: Fill nulls — products with no orders/reviews ──
    product_perf["units_sold"]    = product_perf["units_sold"].fillna(0).astype(int)
    product_perf["total_revenue"] = product_perf["total_revenue"].fillna(0).round(2)
    product_perf["order_count"]   = product_perf["order_count"].fillna(0).astype(int)
    product_perf["review_count"]  = product_perf["review_count"].fillna(0).astype(int)
    # avg_rating stays NaN for products with no reviews — intentional

    # ── Step 5: Rank within category ──────────────────────
    # rank(ascending=False) gives rank 1 to the highest value
    # method="min" gives tied products the same rank
    product_perf["revenue_rank_in_category"] = (
        product_perf
        .groupby("category")["total_revenue"]
        .rank(ascending=False, method="min")
        .astype(int)
    )

    # ── Step 6: Performance tier using pd.qcut ────────────
    # qcut splits into equal-sized buckets based on quantiles
    # duplicates="drop" handles cases where multiple products have identical revenue
    product_perf["performance_tier"] = pd.qcut(
        product_perf["total_revenue"],
        q=4,
        labels=["Bottom 25%", "Lower Mid", "Upper Mid", "Top 25%"],
        duplicates="drop",
    )

    # ── Print ──────────────────────────────────────────────
    print("\nTop 15 products by total revenue:\n")
    top15 = (
        product_perf
        .nlargest(15, "total_revenue")
        [["product_name", "category", "units_sold",
          "total_revenue", "avg_rating", "review_count", "revenue_rank_in_category"]]
    )
    print(top15.to_string(index=False))

    print("\nCategory performance summary:\n")
    cat_summary = (
        product_perf
        .groupby("category")
        .agg(
            products      = ("product_id",    "count"),
            total_revenue = ("total_revenue", "sum"),
            avg_rating    = ("avg_rating",    "mean"),
            total_units   = ("units_sold",    "sum"),
        )
        .sort_values("total_revenue", ascending=False)
        .round(2)
    )
    print(cat_summary.to_string())

    # Save
    out = REPORTS / "analysis3_product_performance.csv"
    product_perf.to_csv(out, index=False)
    logger.info(f"Saved → {out}")

    return product_perf


# ─────────────────────────────────────────────────────────────
# ANALYSIS 4 — Discount Impact Analysis
# ─────────────────────────────────────────────────────────────

def analysis_discount_impact(orders: pd.DataFrame) -> pd.DataFrame:
    """
    Compare orders with and without discounts across:
      - Average order value (AOV)
      - Completion rate (status == 'completed')
      - Return rate (status == 'returned')

    Uses groupby with multiple aggregation functions.
    No loops — all vectorized.
    """
    print("\n" + "=" * 60)
    print("  ANALYSIS 4 — Discount Impact Analysis")
    print("=" * 60)

    # ── Step 1: Create discount tier column ───────────────
    # discount_pct is already filled with 0.0 for no-discount orders
    bins   = [-0.1, 0, 5, 10, 15, 100]
    labels = ["No discount", "1–5%", "6–10%", "11–15%", "16%+"]
    orders = orders.copy()
    orders["discount_tier"] = pd.cut(
        orders["discount_pct"],
        bins=bins,
        labels=labels,
        right=True,
    )

    # ── Step 2: Boolean flag columns for aggregation ──────
    # Vectorized comparison — no loops
    orders["is_completed"] = (orders["status"] == "completed").astype(int)
    orders["is_returned"]  = (orders["status"] == "returned").astype(int)
    orders["is_cancelled"] = (orders["status"] == "cancelled").astype(int)

    # ── Step 3: Aggregate with multiple functions ──────────
    discount_impact = (
        orders
        .groupby("discount_tier", observed=True)
        .agg(
            order_count       = ("order_id",       "count"),
            avg_order_value   = ("total_amount",   "mean"),
            median_order_value= ("total_amount",   "median"),
            total_revenue     = ("total_amount",   "sum"),
            completion_rate   = ("is_completed",   "mean"),   # mean of 0/1 = proportion
            return_rate       = ("is_returned",    "mean"),
            cancellation_rate = ("is_cancelled",   "mean"),
        )
        .round(4)
        .reset_index()
    )

    # ── Step 4: Convert rates to percentages ──────────────
    for col in ["completion_rate", "return_rate", "cancellation_rate"]:
        discount_impact[col] = (discount_impact[col] * 100).round(2)

    discount_impact["avg_order_value"]    = discount_impact["avg_order_value"].round(2)
    discount_impact["median_order_value"] = discount_impact["median_order_value"].round(2)
    discount_impact["total_revenue"]      = discount_impact["total_revenue"].round(2)

    # ── Print ──────────────────────────────────────────────
    print("\nDiscount impact on order behaviour:\n")
    print(discount_impact.to_string(index=False))

    # ── Step 5: Simple has_discount binary comparison ─────
    print("\nDiscounted vs non-discounted orders:\n")
    orders["has_discount"] = orders["discount_pct"] > 0
    binary = (
        orders
        .groupby("has_discount")
        .agg(
            order_count       = ("order_id",     "count"),
            avg_order_value   = ("total_amount", "mean"),
            completion_rate   = ("is_completed", "mean"),
            return_rate       = ("is_returned",  "mean"),
        )
        .round(4)
    )
    binary["completion_rate"] = (binary["completion_rate"] * 100).round(2)
    binary["return_rate"]     = (binary["return_rate"]     * 100).round(2)
    binary["avg_order_value"] = binary["avg_order_value"].round(2)
    binary.index = ["No discount", "Has discount"]
    print(binary.to_string())

    # Save
    out = REPORTS / "analysis4_discount_impact.csv"
    discount_impact.to_csv(out, index=False)
    logger.info(f"Saved → {out}")

    return discount_impact


# ─────────────────────────────────────────────────────────────
# ANALYSIS 5 — Data Quality Report
# ─────────────────────────────────────────────────────────────

def analysis_data_quality_report() -> pd.DataFrame:
    """
    Produce a structured summary of every data quality issue
    found and fixed in Step 1.
    Exported as a CSV for documentation purposes.
    """
    print("\n" + "=" * 60)
    print("  ANALYSIS 5 — Data Quality Report")
    print("=" * 60)

    records = [
        # ORDERS
        ("orders", "Exact duplicate rows",             5,   "Dropped — kept first occurrence"),
        ("orders", "Duplicate order_ids",              5,   "Dropped — kept first occurrence"),
        ("orders", "Mixed date formats",            1010,   "Standardized to YYYY-MM-DD"),
        ("orders", "Currency symbols in unit_price",1010,   "Stripped — converted to float"),
        ("orders", "Inconsistent status casing",    1010,   "Normalized to lowercase canonical values"),
        ("orders", "Inconsistent payment casing",   1010,   "Normalized to lowercase canonical values"),
        ("orders", "Null customer_id",                 6,   "Dropped — FK integrity required"),
        ("orders", "Null product_id",                  3,   "Dropped — FK integrity required"),
        ("orders", "Null shipping_address_city",       49,  "Kept as NaN — analytics only, not critical"),
        ("orders", "Null discount_pct",               393,  "Filled with 0.0 — null implies no discount"),
        ("orders", "Negative or zero quantity",         3,  "Dropped — nonsensical order"),
        ("orders", "Orphaned customer_id (CUST-9xxx)", 15,  "Dropped — no matching customer record"),
        ("orders", "Orphaned product_id",              70,  "Dropped — no matching product record"),

        # CUSTOMERS
        ("customers", "Exact duplicate rows",           3,  "Dropped — kept first occurrence"),
        ("customers", "Duplicate customer_ids",         3,  "Dropped — kept first occurrence"),
        ("customers", "Mixed signup_date formats",    200,   "Standardized to YYYY-MM-DD"),
        ("customers", "is_active mixed types",        203,   "Normalized to boolean (True/False)"),
        ("customers", "Null email",                     4,  "Kept — added has_email flag column"),
        ("customers", "Null loyalty_tier",             36,  "Filled with 'none'"),
        ("customers", "Null postal_code",               3,  "Kept as NaN — not critical"),
        ("customers", "Inconsistent name casing",     203,   "Normalized to Title Case"),

        # PRODUCTS
        ("products", "Exact duplicate rows",            1,  "Dropped"),
        ("products", "Duplicate product_ids",           1,  "Dropped — kept first occurrence"),
        ("products", "Duplicate SKUs",                  3,  "Dropped — kept first occurrence"),
        ("products", "HTML tags in product_name",       3,  "Stripped using BeautifulSoup"),
        ("products", "Null category",                   3,  "Filled with 'uncategorized'"),
        ("products", "Zero or negative unit_price",     2,  "Dropped — invalid product price"),
        ("products", "Null weight_kg",                  2,  "Kept as NaN — optional field"),
        ("products", "Negative stock_quantity",         1,  "Clamped to 0 at DB load stage"),

        # REVIEWS
        ("reviews", "Duplicate review_ids",             3,  "Dropped — kept first occurrence"),
        ("reviews", "Ratings in 33 different formats", 500, "Normalized to float 1.0–5.0"),
        ("reviews", "Out-of-range ratings (e.g. 5.3)", 12,  "Capped at 5.0 — likely rounding artefacts"),
        ("reviews", "verified_purchase in 10 formats", 500, "Normalized to boolean (True/False)"),
        ("reviews", "Null review_text",                39,  "Kept — added has_review_text flag column"),
        ("reviews", "Null helpful_votes",              58,  "Filled with 0"),
        ("reviews", "Orphaned product_id",             42,  "Dropped — no matching product record"),
    ]

    dq_report = pd.DataFrame(records, columns=[
        "table", "issue_type", "rows_affected", "action_taken"
    ])

    # ── Summary by table ───────────────────────────────────
    print("\nData quality issues by table:\n")
    summary = (
        dq_report
        .groupby("table")
        .agg(
            issues_found  = ("issue_type",    "count"),
            rows_affected = ("rows_affected", "sum"),
        )
        .reset_index()
    )
    print(summary.to_string(index=False))

    print(f"\nTotal issues documented: {len(dq_report)}")
    print(f"Total rows affected    : {dq_report['rows_affected'].sum():,}")

    print("\nFull report:\n")
    print(dq_report.to_string(index=False))

    # Save
    out = REPORTS / "analysis5_data_quality_report.csv"
    dq_report.to_csv(out, index=False)
    logger.info(f"Saved → {out}")

    return dq_report


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  STEP 3 — PANDAS ANALYTICS & DATAFRAME OPERATIONS")
    print("=" * 60)

    data = load_data()
    orders    = data["orders"]
    products  = data["products"]
    customers = data["customers"]
    reviews   = data["reviews"]

    revenue_pivot    = analysis_revenue(orders, products)
    customer_summary = analysis_customer_segmentation(orders, customers)
    product_perf     = analysis_product_performance(orders, products, reviews)
    discount_impact  = analysis_discount_impact(orders)
    dq_report        = analysis_data_quality_report()

    print("\n" + "=" * 60)
    print("  ALL ANALYSES COMPLETE")
    print("  Output files saved to data/processed/")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
