# Databricks notebook source
# Silver Layer — Products
# ========================
# Transforms bronze.raw_products into silver.products.
# Enriches with is_slow_mover flag (no transactions in last 90 days).
# Flags orphaned SKUs — stock codes in transactions with no product record.
#
# Unity Catalog namespace: retail_prod.silver.*

import dlt
from pyspark.sql import functions as F

PRODUCT_EXPECTATIONS = {
    "stock_code_not_null":     "stock_code IS NOT NULL",
    "avg_unit_price_positive": "avg_unit_price > 0",
}

# ---------------------------------------------------------------------------
# Silver products
# ---------------------------------------------------------------------------

@dlt.table(
    name="products",
    comment="Clean product catalogue. Includes is_slow_mover flag and is_orphaned_sku flag.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "silver",
    }
)
@dlt.expect_all_or_drop(PRODUCT_EXPECTATIONS)
def silver_products():
    products = (
        dlt.read("raw_products")
            .withColumn(
                "category",
                F.when(
                    F.col("category").isNull() | (F.trim(F.col("category")) == ""),
                    F.lit("Uncategorized")
                ).otherwise(F.col("category"))
            )
            .withColumn("description", F.trim(F.col("description")))
            .dropDuplicates(["stock_code"])
    )

    # Compute slow movers: SKUs with no transactions in the last 90 days
    tx = dlt.read("transactions")
    ninety_days_ago = F.date_sub(F.current_date(), 90)

    recent_active_skus = (
        tx.filter(F.col("invoice_date") >= ninety_days_ago)
          .select("stock_code")
          .distinct()
    )

    # All SKUs in transactions (to flag orphans) — use join, not .collect()
    all_tx_skus = tx.select("stock_code").distinct().withColumn("_in_tx", F.lit(True))

    enriched = (
        products
            .join(recent_active_skus, on="stock_code", how="left_anti")
            .withColumn("is_slow_mover", F.lit(True))
            .unionByName(
                products.join(recent_active_skus, on="stock_code", how="inner")
                        .withColumn("is_slow_mover", F.lit(False))
            )
    )

    return (
        enriched
            .join(all_tx_skus, on="stock_code", how="left")
            .withColumn(
                "is_orphaned_sku",
                F.col("_in_tx").isNull()   # no matching tx row → orphaned
            )
            .drop("_in_tx")
            .withColumn("_transformed_at", F.current_timestamp())
    )
