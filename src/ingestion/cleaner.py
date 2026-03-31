"""
cleaner.py
----------
Cleaning pipeline for all four raw datasets.

Design principles:
  - Every function is pure: same input → same output (repeatable)
  - Issues are LOGGED before being fixed or dropped, never silently swallowed
  - Decisions (drop vs fill vs flag) are documented inline with reasoning
  - Vectorized pandas operations are used throughout — no row-by-row loops
  - Each clean_*() function returns a NEW DataFrame (original is never mutated)
"""

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


# ─────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────

def _parse_date(value: str) -> pd.Timestamp | None:
    """
    Parse a date string that may be in any of these formats:
      - YYYY-MM-DD        e.g. 2024-03-22
      - DD/MM/YYYY        e.g. 29/10/2024
      - MM/DD/YYYY        e.g. 07/01/2024  (ambiguous — handled below)
      - MM-DD-YYYY        e.g. 06-17-2021
      - DD Mon YYYY       e.g. 17 May 2023
      - Mon DD, YYYY      e.g. Jul 26, 2024
      - Month DD, YYYY    e.g. January 18, 2024
      - September 28, 2023

    Ambiguous DD/MM vs MM/DD is resolved by trying DD/MM first (international
    data from Middle East / global customers), then falling back to MM/DD.
    Returns None if unparseable so callers can log the failure.
    """
    if pd.isna(value) or str(value).strip() == "":
        return None

    value = str(value).strip()

    # Try ISO format first (unambiguous)
    try:
        return pd.Timestamp(value)
    except Exception:
        pass

    # Try DD/MM/YYYY and DD-MM-YYYY
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y",
                "%d %b %Y", "%b %d, %Y", "%B %d, %Y", "%B %d %Y"):
        try:
            return pd.Timestamp(pd.to_datetime(value, format=fmt))
        except Exception:
            pass

    # Last resort: pandas inference
    try:
        return pd.Timestamp(pd.to_datetime(value, infer_datetime_format=True))
    except Exception:
        return None


def _clean_price(value: str) -> float | None:
    """
    Strip currency symbols and text, return a float.
    Handles: '$202.12', 'AED 58.37', '50.22 USD', '136.22'
    Returns None if value cannot be converted.
    """
    if pd.isna(value) or str(value).strip() == "":
        return None
    # Remove currency symbols, codes, and whitespace
    cleaned = re.sub(r"[^\d.]", "", str(value).strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_bool(value) -> bool | None:
    """
    Normalize is_active field which can be True/False/bool, 'yes'/'no', 1/0.
    Returns True, False, or None for truly ambiguous values.
    """
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    val = str(value).strip().lower()
    if val in ("true", "yes", "1"):
        return True
    if val in ("false", "no", "0"):
        return False
    return None


def _strip_html(value: str) -> str:
    """
    Remove HTML tags from a string using BeautifulSoup.
    e.g. '<b>Mechanical Keyboard RGB</b>' → 'Mechanical Keyboard RGB'
    """
    if pd.isna(value):
        return value
    return BeautifulSoup(str(value), "html.parser").get_text().strip()


def _normalize_rating(value: str) -> float | None:
    """
    Normalize ratings from any of these formats to a float on 1–5 scale:
      '4', '4.0', '4/5', '5/5', 'four', 'five', 'three', 'two', 'one'
    Returns None if unparseable. Caps at 5.0, floors at 1.0.
    """
    if pd.isna(value) or str(value).strip() == "":
        return None

    word_map = {
        "one": 1.0, "two": 2.0, "three": 3.0,
        "four": 4.0, "five": 5.0
    }
    val = str(value).strip().lower()

    if val in word_map:
        return word_map[val]

    # Handle 'X/5' format
    if "/" in val:
        try:
            numerator, denominator = val.split("/")
            result = float(numerator) / float(denominator) * 5
            return round(min(max(result, 1.0), 5.0), 2)
        except Exception:
            return None

    # Plain float/int
    try:
        result = float(val)
        # Out-of-range values (e.g. 5.3) are capped rather than dropped
        # Reasoning: likely rounding artefacts, not fundamentally invalid data
        return round(min(max(result, 1.0), 5.0), 2)
    except ValueError:
        return None


def _normalize_verified(value: str) -> bool | None:
    """
    Normalize verified_purchase from: True/False/Yes/No/Y/N/yes/no/1/0
    """
    if pd.isna(value):
        return None
    val = str(value).strip().lower()
    if val in ("true", "yes", "y", "1"):
        return True
    if val in ("false", "no", "n", "0"):
        return False
    return None


# ─────────────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────────────

def clean_orders(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean orders_raw DataFrame.

    Issues addressed:
      1. Exact duplicate rows → drop, keep first
      2. Duplicate order_ids → drop duplicates, keep first
      3. Mixed date formats → standardize to YYYY-MM-DD
      4. unit_price with currency symbols → strip to float
      5. status / payment_method casing → normalize to lowercase + consolidate
      6. Null customer_id / product_id → DROP (can't have orphaned orders)
      7. Null shipping_address_city → KEEP as NaN (city is not critical)
      8. Null discount_pct → FILL with 0.0 (null means no discount was applied)
      9. Negative or zero quantity → LOG and DROP (nonsensical orders)
     10. Orphaned foreign keys → LOG and DROP after cross-validation in pipeline
    """
    df = df.copy()
    initial_rows = len(df)

    # ── Normalize column names ──────────────────────────────
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # ── 1. Drop exact duplicate rows ───────────────────────
    dupes = df.duplicated().sum()
    if dupes:
        logger.warning(f"[orders] Dropping {dupes} exact duplicate rows")
    df.drop_duplicates(inplace=True)

    # ── 2. Deduplicate on order_id (keep first occurrence) ─
    id_dupes = df.duplicated(subset=["order_id"]).sum()
    if id_dupes:
        logger.warning(f"[orders] Dropping {id_dupes} rows with duplicate order_id")
    df.drop_duplicates(subset=["order_id"], keep="first", inplace=True)

    # ── 3. Standardize order_date to YYYY-MM-DD ────────────
    parsed_dates = df["order_date"].map(_parse_date)
    unparseable = parsed_dates.isna().sum()
    if unparseable:
        logger.warning(f"[orders] {unparseable} order_date values could not be parsed → set to NaT")
    df["order_date"] = parsed_dates.dt.strftime("%Y-%m-%d")

    # ── 4. Clean unit_price → float ────────────────────────
    df["unit_price"] = df["unit_price"].map(_clean_price)
    bad_price = df["unit_price"].isna().sum()
    if bad_price:
        logger.warning(f"[orders] {bad_price} unit_price values could not be parsed → NaN")

    # ── 5a. Normalize status ────────────────────────────────
    # Map all variants to a canonical lowercase set
    status_map = {
        "completed": "completed",
        "complete": "completed",
        "COMPLETED": "completed",
        "shipped": "shipped",
        "Shipped": "shipped",
        "processing": "processing",
        "pending": "pending",
        "Pending": "pending",
        "returned": "returned",
        "cancelled": "cancelled",
        "Canceled": "cancelled",
        "canceled": "cancelled",
        "delivered": "delivered",
        "DELIVERED": "delivered",
    }
    df["status"] = df["status"].str.strip().str.lower().map(
        lambda x: status_map.get(x, x)  # unknown values pass through for review
    )

    # ── 5b. Normalize payment_method ───────────────────────
    payment_map = {
        "paypal": "paypal",
        "apple_pay": "apple_pay",
        "applepay": "apple_pay",
        "credit_card": "credit_card",
        "credit card": "credit_card",
        "debit_card": "debit_card",
        "cash_on_delivery": "cash_on_delivery",
        "bank_transfer": "bank_transfer",
    }
    df["payment_method"] = df["payment_method"].str.strip().str.lower().map(
        lambda x: payment_map.get(x, x)
    )

    # ── 6. Drop rows with null customer_id or product_id ───
    # Reasoning: an order without a customer or product is meaningless
    # and would break FK constraints in the database
    null_cust = df["customer_id"].isna().sum()
    null_prod = df["product_id"].isna().sum()
    if null_cust:
        logger.warning(f"[orders] Dropping {null_cust} rows with null customer_id")
    if null_prod:
        logger.warning(f"[orders] Dropping {null_prod} rows with null product_id")
    df.dropna(subset=["customer_id", "product_id"], inplace=True)

    # ── 7. Null shipping_address_city → keep as NaN ────────
    # Reasoning: city is for analytics only, not required for order integrity
    null_city = df["shipping_address_city"].isna().sum()
    if null_city:
        logger.info(f"[orders] {null_city} rows have null shipping_address_city — kept as NaN")

    # ── 8. Fill null discount_pct with 0.0 ─────────────────
    # Reasoning: absence of discount_pct strongly implies no discount was applied
    df["discount_pct"] = pd.to_numeric(df["discount_pct"], errors="coerce").fillna(0.0)

    # ── 9. Remove negative or zero quantity rows ───────────
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    bad_qty = df[df["quantity"] <= 0]
    if len(bad_qty):
        logger.warning(
            f"[orders] Dropping {len(bad_qty)} rows with quantity <= 0. "
            f"order_ids: {bad_qty['order_id'].tolist()}"
        )
    df = df[df["quantity"] > 0]

    # ── Cast types ─────────────────────────────────────────
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["quantity"] = df["quantity"].astype(int)

    df.reset_index(drop=True, inplace=True)
    logger.info(f"[orders] Cleaned: {initial_rows} → {len(df)} rows")
    return df


# ─────────────────────────────────────────────────────────────
# CUSTOMERS
# ─────────────────────────────────────────────────────────────

def clean_customers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean customers DataFrame (already flattened by json_normalize in loader).

    Issues addressed:
      1. Rename nested columns (name.first → first_name, address.city → city)
      2. Exact duplicate rows → drop
      3. Duplicate customer_id → drop, keep first
      4. Normalize name casing → Title Case
      5. Null email → KEEP, add has_email flag (customer valid without email)
      6. Mixed signup_date formats → YYYY-MM-DD
      7. is_active as bool/string/int → normalize to True/False
      8. Null loyalty_tier → FILL with 'none' (meaningful absence of tier)
      9. Null postal_code → KEEP as NaN (not critical)
    """
    df = df.copy()
    initial_rows = len(df)

    # ── 1. Rename flattened nested columns ──────────────────
    df.rename(columns={
        "name.first": "first_name",
        "name.last": "last_name",
        "address.city": "city",
        "address.country": "country",
        "address.postal_code": "postal_code",
    }, inplace=True)

    # ── 2. Drop exact duplicate rows ───────────────────────
    dupes = df.duplicated().sum()
    if dupes:
        logger.warning(f"[customers] Dropping {dupes} exact duplicate rows")
    df.drop_duplicates(inplace=True)

    # ── 3. Deduplicate on customer_id ─────────────────────
    id_dupes = df.duplicated(subset=["customer_id"]).sum()
    if id_dupes:
        logger.warning(f"[customers] Dropping {id_dupes} rows with duplicate customer_id")
    df.drop_duplicates(subset=["customer_id"], keep="first", inplace=True)

    # ── 4. Normalize name casing ───────────────────────────
    df["first_name"] = df["first_name"].str.strip().str.title()
    df["last_name"] = df["last_name"].str.strip().str.title()

    # ── 5. Null email handling ─────────────────────────────
    # Flag it but keep the row — email is not mandatory to be a customer
    df["email"] = df["email"].str.strip().str.lower()
    df["has_email"] = df["email"].notna()
    null_email = (~df["has_email"]).sum()
    if null_email:
        logger.info(f"[customers] {null_email} customers have no email — flagged, rows kept")

    # ── 6. Standardize signup_date ────────────────────────
    parsed_dates = df["signup_date"].map(_parse_date)
    unparseable = parsed_dates.isna().sum()
    if unparseable:
        logger.warning(f"[customers] {unparseable} signup_date values could not be parsed → NaT")
    df["signup_date"] = parsed_dates.dt.strftime("%Y-%m-%d")

    # ── 7. Normalize is_active → bool ─────────────────────
    df["is_active"] = df["is_active"].map(_normalize_bool)
    bad_active = df["is_active"].isna().sum()
    if bad_active:
        logger.warning(f"[customers] {bad_active} is_active values could not be normalized → NaN")

    # ── 8. Fill null loyalty_tier ─────────────────────────
    # 'none' is used (not NaN) so it can be stored as a proper category
    null_tier = df["loyalty_tier"].isna().sum()
    if null_tier:
        logger.info(f"[customers] {null_tier} customers have no loyalty_tier → filled with 'none'")
    df["loyalty_tier"] = df["loyalty_tier"].fillna("none").str.strip().str.lower()

    # ── 9. Null postal_code — keep as NaN ─────────────────
    null_postal = df["postal_code"].isna().sum()
    if null_postal:
        logger.info(f"[customers] {null_postal} null postal_codes — kept as NaN")

    # ── Normalize city/country casing ─────────────────────
    df["city"] = df["city"].str.strip().str.title()
    df["country"] = df["country"].str.strip().str.title()

    df.reset_index(drop=True, inplace=True)
    logger.info(f"[customers] Cleaned: {initial_rows} → {len(df)} rows")
    return df


# ─────────────────────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────────────────────

def clean_products(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean products_raw DataFrame.

    Issues addressed:
      1. Normalize column names
      2. Exact duplicate rows → drop
      3. Duplicate product_id → drop, keep first
      4. Duplicate SKUs → log and keep first
      5. Strip HTML tags from product_name
      6. Normalize product_name casing (Title Case) and strip whitespace
      7. Null category → FILL with 'uncategorized'
      8. Zero/negative unit_price → LOG and DROP (can't sell at invalid price)
      9. Null weight_kg → KEEP as NaN (weight missing is not fatal)
     10. Parse numeric columns properly
    """
    df = df.copy()
    initial_rows = len(df)

    # ── 1. Normalize column names ──────────────────────────
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # ── 2. Drop exact duplicate rows ───────────────────────
    dupes = df.duplicated().sum()
    if dupes:
        logger.warning(f"[products] Dropping {dupes} exact duplicate rows")
    df.drop_duplicates(inplace=True)

    # ── 3. Deduplicate on product_id ──────────────────────
    id_dupes = df.duplicated(subset=["product_id"]).sum()
    if id_dupes:
        logger.warning(f"[products] Dropping {id_dupes} rows with duplicate product_id")
    df.drop_duplicates(subset=["product_id"], keep="first", inplace=True)

    # ── 4. Log duplicate SKUs and keep first ──────────────
    sku_dupes = df.duplicated(subset=["sku"]).sum()
    if sku_dupes:
        dup_skus = df[df.duplicated(subset=["sku"], keep=False)]["sku"].unique().tolist()
        logger.warning(
            f"[products] {sku_dupes} duplicate SKUs found: {dup_skus} — keeping first occurrence"
        )
    df.drop_duplicates(subset=["sku"], keep="first", inplace=True)

    # ── 5. Strip HTML tags from product_name ──────────────
    html_rows = df["product_name"].str.contains("<", na=False).sum()
    if html_rows:
        logger.info(f"[products] Stripping HTML from {html_rows} product_name values")
    df["product_name"] = df["product_name"].map(_strip_html)

    # ── 6. Normalize product_name ─────────────────────────
    df["product_name"] = df["product_name"].str.strip().str.title()

    # ── 7. Fill null category ─────────────────────────────
    null_cat = df["category"].isna().sum()
    if null_cat:
        logger.info(f"[products] {null_cat} null categories → filled with 'uncategorized'")
    df["category"] = (
        df["category"]
        .fillna("uncategorized")
        .str.strip()
        .str.lower()
    )

    # ── 8. Parse unit_price, drop invalid values ──────────
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    bad_price = df[df["unit_price"] <= 0]
    if len(bad_price):
        logger.warning(
            f"[products] Dropping {len(bad_price)} products with unit_price <= 0. "
            f"product_ids: {bad_price['product_id'].tolist()}"
        )
    df = df[df["unit_price"] > 0]

    # ── 9. Null weight_kg — keep as NaN ───────────────────
    df["weight_kg"] = pd.to_numeric(df["weight_kg"], errors="coerce")
    null_weight = df["weight_kg"].isna().sum()
    if null_weight:
        logger.info(f"[products] {null_weight} null weight_kg values — kept as NaN")

    # ── 10. Parse remaining numeric columns ───────────────
    df["stock_quantity"] = pd.to_numeric(df["stock_quantity"], errors="coerce").fillna(0).astype(int)

    # Standardize created_date
    df["created_date"] = df["created_date"].map(_parse_date).dt.strftime("%Y-%m-%d")

    df.reset_index(drop=True, inplace=True)
    logger.info(f"[products] Cleaned: {initial_rows} → {len(df)} rows")
    return df


# ─────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────

def clean_reviews(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean reviews_raw DataFrame.

    Issues addressed:
      1. Duplicate review_id → drop, keep first
      2. Rating normalization: '4', '4/5', 'four', '4.0', '5.3' → float 1–5
      3. verified_purchase normalization: mixed → True/False
      4. Null review_text → KEEP, add has_review_text flag
      5. Null helpful_votes → FILL with 0 (no vote = 0 votes)
      6. Standardize review_date → YYYY-MM-DD
      7. Orphaned product_ids → logged in validator, not dropped here
    """
    df = df.copy()
    initial_rows = len(df)

    # ── Normalize column names ─────────────────────────────
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # ── 1. Deduplicate review_id ──────────────────────────
    id_dupes = df.duplicated(subset=["review_id"]).sum()
    if id_dupes:
        logger.warning(f"[reviews] Dropping {id_dupes} rows with duplicate review_id")
    df.drop_duplicates(subset=["review_id"], keep="first", inplace=True)

    # ── 2. Normalize rating → float ───────────────────────
    df["rating"] = df["rating"].map(_normalize_rating)
    bad_rating = df["rating"].isna().sum()
    if bad_rating:
        logger.warning(f"[reviews] {bad_rating} rating values could not be parsed → NaN")

    # ── 3. Normalize verified_purchase ────────────────────
    df["verified_purchase"] = df["verified_purchase"].map(_normalize_verified)
    bad_verified = df["verified_purchase"].isna().sum()
    if bad_verified:
        logger.warning(f"[reviews] {bad_verified} verified_purchase values could not be parsed → NaN")

    # ── 4. Null review_text — keep, flag ──────────────────
    df["has_review_text"] = df["review_text"].notna() & (df["review_text"].str.strip() != "")
    null_text = (~df["has_review_text"]).sum()
    if null_text:
        logger.info(f"[reviews] {null_text} reviews have no text — flagged, rows kept")

    # ── 5. Fill null helpful_votes with 0 ─────────────────
    # Reasoning: a review that received no votes has 0 helpful votes
    df["helpful_votes"] = pd.to_numeric(df["helpful_votes"], errors="coerce").fillna(0).astype(int)

    # ── 6. Standardize review_date ───────────────────────
    df["review_date"] = df["review_date"].map(_parse_date).dt.strftime("%Y-%m-%d")

    df.reset_index(drop=True, inplace=True)
    logger.info(f"[reviews] Cleaned: {initial_rows} → {len(df)} rows")
    return df


# ─────────────────────────────────────────────────────────────
# PIPELINE ENTRY POINT
# ─────────────────────────────────────────────────────────────

def clean_all(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Run the full cleaning pipeline on all four raw DataFrames.
    Also removes cross-dataset orphaned foreign keys after individual cleaning.

    Parameters
    ----------
    raw : dict returned by loader.load_all()

    Returns
    -------
    dict of cleaned DataFrames keyed by name
    """
    cleaned_customers = clean_customers(raw["customers"])
    cleaned_products = clean_products(raw["products"])
    cleaned_orders = clean_orders(raw["orders"])
    cleaned_reviews = clean_reviews(raw["reviews"])

    # ── Cross-dataset FK validation and cleanup ────────────
    valid_customer_ids = set(cleaned_customers["customer_id"])
    valid_product_ids = set(cleaned_products["product_id"])

    # Orders: drop orphaned customer_id references
    orphan_cust = ~cleaned_orders["customer_id"].isin(valid_customer_ids)
    if orphan_cust.sum():
        logger.warning(
            f"[pipeline] Dropping {orphan_cust.sum()} orders with customer_id "
            f"not found in customers table: "
            f"{cleaned_orders.loc[orphan_cust, 'customer_id'].unique().tolist()}"
        )
    cleaned_orders = cleaned_orders[~orphan_cust].reset_index(drop=True)

    # Orders: drop orphaned product_id references
    orphan_prod_orders = ~cleaned_orders["product_id"].isin(valid_product_ids)
    if orphan_prod_orders.sum():
        logger.warning(
            f"[pipeline] Dropping {orphan_prod_orders.sum()} orders with product_id "
            f"not found in products table: "
            f"{cleaned_orders.loc[orphan_prod_orders, 'product_id'].unique().tolist()}"
        )
    cleaned_orders = cleaned_orders[~orphan_prod_orders].reset_index(drop=True)

    # Reviews: drop orphaned product_id references
    orphan_prod_reviews = ~cleaned_reviews["product_id"].isin(valid_product_ids)
    if orphan_prod_reviews.sum():
        logger.warning(
            f"[pipeline] Dropping {orphan_prod_reviews.sum()} reviews with product_id "
            f"not found in products table: "
            f"{cleaned_reviews.loc[orphan_prod_reviews, 'product_id'].unique().tolist()}"
        )
    cleaned_reviews = cleaned_reviews[~orphan_prod_reviews].reset_index(drop=True)

    return {
        "customers": cleaned_customers,
        "products": cleaned_products,
        "orders": cleaned_orders,
        "reviews": cleaned_reviews,
    }
