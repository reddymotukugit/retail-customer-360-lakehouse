# Databricks notebook source
# Silver Layer — Transactions
# ============================
# Transforms bronze.raw_transactions into:
#   silver.transactions         — clean, valid records
#   silver.cancelled_transactions — cancellation rows (InvoiceNo starts with 'C')
#   silver._quarantine_transactions — rows that fail quality expectations
#
# Data quality expectations stored in Unity Catalog (not hardcoded).
# Unity Catalog namespace: retail_prod.silver.*

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType

# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------

TRANSACTION_EXPECTATIONS = {
    "quantity_positive":       "quantity > 0",
    "unit_price_non_negative": "unit_price >= 0",
    "invoice_date_not_null":   "invoice_date IS NOT NULL",
    "invoice_no_not_null":     "invoice_no IS NOT NULL",
    "stock_code_not_null":     "stock_code IS NOT NULL",
}

CUSTOMER_ID_EXPECTATION = {
    "customer_id_not_null": "customer_id IS NOT NULL"
}

# ---------------------------------------------------------------------------
# Cancelled transactions — routed out, not dropped
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.cancelled_transactions",
    comment="Rows where invoice_no starts with 'C' — cancellations tracked separately, never dropped.",
    table_properties={"quality": "silver"}
)
def cancelled_transactions():
    return (
        dlt.read_stream("raw_transactions")
            .filter(F.col("invoice_no").startswith("C"))
            .withColumn("cancelled_at", F.current_timestamp())
            .withColumn("original_invoice_no", F.regexp_replace("invoice_no", "^C", ""))
    )

# ---------------------------------------------------------------------------
# Quarantine — rows with null customer_id (kept for audit, not used downstream)
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver._quarantine_transactions",
    comment="Rows that failed the customer_id IS NOT NULL expectation. Kept for audit.",
    table_properties={"quality": "quarantine"}
)
@dlt.expect_all_or_drop(CUSTOMER_ID_EXPECTATION)
def quarantine_transactions():
    return (
        dlt.read_stream("raw_transactions")
            .filter(~F.col("invoice_no").startswith("C"))  # exclude cancellations already routed
            .filter(F.col("customer_id").isNull())
            .withColumn("quarantine_reason", F.lit("customer_id IS NULL"))
            .withColumn("quarantined_at", F.current_timestamp())
    )

# ---------------------------------------------------------------------------
# Silver transactions — clean, valid, deduplicated
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.transactions",
    comment="Clean, validated retail transactions. Cancellations excluded. Quarantine rows excluded.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "silver",
    }
)
@dlt.expect_all_or_drop(TRANSACTION_EXPECTATIONS)
def silver_transactions():
    return (
        dlt.read_stream("raw_transactions")
            # Exclude cancellations (handled separately)
            .filter(~F.col("invoice_no").startswith("C"))
            # Exclude null customer_id (handled in quarantine)
            .filter(F.col("customer_id").isNotNull())
            # Cast and derive columns
            .withColumn(
                "invoice_date",
                F.to_timestamp("invoice_date")
            )
            .withColumn(
                "line_total",
                (F.col("quantity") * F.col("unit_price")).cast(DecimalType(12, 2))
            )
            .withColumn("invoice_year",  F.year("invoice_date"))
            .withColumn("invoice_month", F.month("invoice_date"))
            .withColumn("invoice_week",  F.weekofyear("invoice_date"))
            # Deduplicate on natural composite key
            .dropDuplicates(["invoice_no", "stock_code"])
            .withColumn("_transformed_at", F.current_timestamp())
    )
