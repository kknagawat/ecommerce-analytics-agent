"""
validator.py
------------
Post-cleaning data quality assertions.

Philosophy:
  - Validators NEVER raise exceptions that stop the pipeline.
  - They LOG every violation so issues are visible without crashing.
  - A final summary reports pass/fail counts.
  - Run this after clean_all() to confirm cleaning worked correctly.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, rule_name: str, condition: bool, failure_msg: str):
        if condition:
            self.passed.append(rule_name)
            logger.info(f"  ✓ PASS  {rule_name}")
        else:
            self.failed.append(rule_name)
            logger.warning(f"  ✗ FAIL  {rule_name}: {failure_msg}")

    def summary(self):
        total = len(self.passed) + len(self.failed)
        logger.info(f"\n{'=' * 50}")
        logger.info(f"  VALIDATION SUMMARY: {len(self.passed)}/{total} rules passed")
        if self.failed:
            logger.warning(f"  Failed rules: {self.failed}")
        logger.info(f"{'=' * 50}\n")
        return {"passed": len(self.passed), "failed": len(self.failed), "total": total}


def validate_customers(df: pd.DataFrame) -> ValidationResult:
    r = ValidationResult()
    logger.info("\n[VALIDATE] customers")

    r.check("no null customer_id",
            df["customer_id"].notna().all(),
            f"{df['customer_id'].isna().sum()} null customer_ids")

    r.check("unique customer_id",
            df["customer_id"].nunique() == len(df),
            f"{df.duplicated(subset=['customer_id']).sum()} duplicate customer_ids")

    r.check("signup_date format",
            df["signup_date"].dropna().str.match(r"^\d{4}-\d{2}-\d{2}$").all(),
            "Some signup_dates are not YYYY-MM-DD format")

    r.check("is_active is boolean",
            df["is_active"].dropna().isin([True, False]).all(),
            "Some is_active values are not boolean")

    r.check("loyalty_tier no nulls",
            df["loyalty_tier"].notna().all(),
            f"{df['loyalty_tier'].isna().sum()} null loyalty_tier values")

    r.check("loyalty_tier valid values",
            df["loyalty_tier"].isin(["platinum", "gold", "silver", "bronze", "none"]).all(),
            f"Unexpected values: {df[~df['loyalty_tier'].isin(['platinum','gold','silver','bronze','none'])]['loyalty_tier'].unique()}")

    return r


def validate_products(df: pd.DataFrame) -> ValidationResult:
    r = ValidationResult()
    logger.info("\n[VALIDATE] products")

    r.check("no null product_id",
            df["product_id"].notna().all(),
            f"{df['product_id'].isna().sum()} null product_ids")

    r.check("unique product_id",
            df["product_id"].nunique() == len(df),
            f"{df.duplicated(subset=['product_id']).sum()} duplicate product_ids")

    r.check("unique sku",
            df["sku"].nunique() == len(df),
            f"{df.duplicated(subset=['sku']).sum()} duplicate SKUs")

    r.check("all prices > 0",
            (df["unit_price"] > 0).all(),
            f"{(df['unit_price'] <= 0).sum()} products with price <= 0")

    r.check("no null category",
            df["category"].notna().all(),
            f"{df['category'].isna().sum()} null categories")

    r.check("no html in product_name",
            ~df["product_name"].str.contains("<", na=False).any(),
            "HTML tags found in product_name")

    r.check("created_date format",
            df["created_date"].dropna().str.match(r"^\d{4}-\d{2}-\d{2}$").all(),
            "Some created_dates are not YYYY-MM-DD format")

    return r


def validate_orders(df: pd.DataFrame,
                    valid_customer_ids: set,
                    valid_product_ids: set) -> ValidationResult:
    r = ValidationResult()
    logger.info("\n[VALIDATE] orders")

    r.check("no null order_id",
            df["order_id"].notna().all(),
            f"{df['order_id'].isna().sum()} null order_ids")

    r.check("unique order_id",
            df["order_id"].nunique() == len(df),
            f"{df.duplicated(subset=['order_id']).sum()} duplicate order_ids")

    r.check("no null customer_id",
            df["customer_id"].notna().all(),
            f"{df['customer_id'].isna().sum()} null customer_ids")

    r.check("no null product_id",
            df["product_id"].notna().all(),
            f"{df['product_id'].isna().sum()} null product_ids")

    r.check("all customer_ids valid FK",
            df["customer_id"].isin(valid_customer_ids).all(),
            f"{(~df['customer_id'].isin(valid_customer_ids)).sum()} orphaned customer_ids")

    r.check("all product_ids valid FK",
            df["product_id"].isin(valid_product_ids).all(),
            f"{(~df['product_id'].isin(valid_product_ids)).sum()} orphaned product_ids")

    r.check("all quantities > 0",
            (df["quantity"] > 0).all(),
            f"{(df['quantity'] <= 0).sum()} orders with quantity <= 0")

    r.check("all unit_prices > 0",
            (df["unit_price"] > 0).all(),
            f"{(df['unit_price'] <= 0).sum()} orders with price <= 0")

    r.check("order_date format",
            df["order_date"].dropna().str.match(r"^\d{4}-\d{2}-\d{2}$").all(),
            "Some order_dates are not YYYY-MM-DD format")

    valid_statuses = {"completed", "shipped", "processing", "pending", "returned", "cancelled", "delivered"}
    r.check("status valid values",
            df["status"].isin(valid_statuses).all(),
            f"Unexpected statuses: {df[~df['status'].isin(valid_statuses)]['status'].unique()}")

    return r


def validate_reviews(df: pd.DataFrame, valid_product_ids: set) -> ValidationResult:
    r = ValidationResult()
    logger.info("\n[VALIDATE] reviews")

    r.check("no null review_id",
            df["review_id"].notna().all(),
            f"{df['review_id'].isna().sum()} null review_ids")

    r.check("unique review_id",
            df["review_id"].nunique() == len(df),
            f"{df.duplicated(subset=['review_id']).sum()} duplicate review_ids")

    r.check("all product_ids valid FK",
            df["product_id"].isin(valid_product_ids).all(),
            f"{(~df['product_id'].isin(valid_product_ids)).sum()} orphaned product_ids")

    r.check("ratings in range 1–5",
            df["rating"].dropna().between(1.0, 5.0).all(),
            f"{(~df['rating'].dropna().between(1.0, 5.0)).sum()} ratings outside 1–5")

    r.check("review_date format",
            df["review_date"].dropna().str.match(r"^\d{4}-\d{2}-\d{2}$").all(),
            "Some review_dates are not YYYY-MM-DD format")

    return r


def validate_all(cleaned: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """
    Run all validators against the cleaned dataset dict.
    Returns a summary dict with pass/fail counts per table.
    """
    logger.info("\n" + "=" * 50)
    logger.info("  RUNNING POST-CLEAN VALIDATION")
    logger.info("=" * 50)

    valid_customer_ids = set(cleaned["customers"]["customer_id"])
    valid_product_ids = set(cleaned["products"]["product_id"])

    results = {
        "customers": validate_customers(cleaned["customers"]).summary(),
        "products": validate_products(cleaned["products"]).summary(),
        "orders": validate_orders(cleaned["orders"], valid_customer_ids, valid_product_ids).summary(),
        "reviews": validate_reviews(cleaned["reviews"], valid_product_ids).summary(),
    }

    total_passed = sum(r["passed"] for r in results.values())
    total_failed = sum(r["failed"] for r in results.values())
    logger.info(f"\n  OVERALL: {total_passed} passed, {total_failed} failed")

    return results
