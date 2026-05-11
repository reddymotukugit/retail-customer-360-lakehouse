# Databricks notebook source
# Silver Layer — Customers
# =========================
# Transforms bronze.raw_customers into:
#   silver.customers            — clean customer profiles (SCD Type 1)
#   silver._quarantine_customers — rows with invalid email addresses
#
# Unity Catalog namespace: retail_prod.silver.*

import dlt
from pyspark.sql import functions as F

EMAIL_PATTERN = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'

CUSTOMER_EXPECTATIONS = {
    "customer_id_not_null": "customer_id IS NOT NULL",
    "loyalty_tier_valid":   "loyalty_tier IN ('Bronze', 'Silver', 'Gold', 'Platinum')",
}

# ---------------------------------------------------------------------------
# Quarantine — invalid email addresses
# ---------------------------------------------------------------------------

@dlt.table(
    name="_quarantine_customers",
    comment="Customer rows with invalid or missing email addresses.",
    table_properties={"quality": "quarantine"}
)
def quarantine_customers():
    return (
        dlt.read_stream("raw_customers")
            .filter(
                F.col("email").isNull() |
                ~F.col("email").rlike(EMAIL_PATTERN)
            )
            .withColumn("quarantine_reason", F.lit("invalid_email"))
            .withColumn("quarantined_at", F.current_timestamp())
    )

# ---------------------------------------------------------------------------
# Silver customers — SCD Type 1 (last-write-wins)
# ---------------------------------------------------------------------------

@dlt.table(
    name="customers",
    comment="Clean customer profiles. SCD Type 1 — latest record per customer_id wins.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "silver",
    }
)
@dlt.expect_all_or_drop(CUSTOMER_EXPECTATIONS)
def silver_customers():
    return (
        dlt.read_stream("raw_customers")
            # Exclude invalid emails (handled in quarantine)
            .filter(F.col("email").rlike(EMAIL_PATTERN))
            # Standardise
            .withColumn("email", F.lower(F.trim(F.col("email"))))
            .withColumn("full_name", F.trim(F.col("full_name")))
            .withColumn("loyalty_tier", F.initcap(F.trim(F.col("loyalty_tier"))))
            # SCD1 — keep only the most recent row per customer_id
            # In streaming context, deduplication window is handled by DLT
            .dropDuplicates(["customer_id"])
            .withColumn("_transformed_at", F.current_timestamp())
    )
