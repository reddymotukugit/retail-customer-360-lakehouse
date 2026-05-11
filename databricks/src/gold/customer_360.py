# Databricks notebook source
# Gold Layer — Customer 360
# ==========================
# One row per customer. Rebuilt daily.
# Joins silver tables and incorporates ML-written back segment labels from MLflow.
#
# Columns written by the ML job (segmentation.py):
#   customer_segment  — business-named cluster (Champions, Loyal, At Risk, Lost)
#   churn_risk_score  — float 0-1 from the logistic model
#
# Unity Catalog namespace: retail_prod.gold.customer_360

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType
from pyspark.sql.window import Window

@dlt.table(
    name="customer_360",
    comment="One row per customer. RFM scores, lifetime value, ML segment label, churn risk. Rebuilt daily.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "gold",
    }
)
def customer_360():
    tx = dlt.read("transactions")
    customers = dlt.read("customers")

    today = F.current_date()

    # ---------------------------------------------------------------------------
    # RFM aggregations per customer
    # ---------------------------------------------------------------------------
    rfm = (
        tx.groupBy("customer_id")
          .agg(
              # Recency — days since last purchase (lower = better)
              F.datediff(today, F.max("invoice_date")).alias("days_since_last_purchase"),
              # Frequency — total distinct invoices
              F.countDistinct("invoice_no").alias("total_orders"),
              # Monetary — lifetime revenue
              F.sum("line_total").cast(DecimalType(14, 2)).alias("total_revenue_lifetime"),
              # First purchase
              F.datediff(today, F.min("invoice_date")).alias("days_since_first_purchase"),
              # Average order value
              (F.sum("line_total") / F.countDistinct("invoice_no")).cast(DecimalType(10, 2)).alias("avg_order_value"),
          )
    )

    # Most frequent country per customer (derived from transactions, not customer profile)
    customer_country = (
        tx.groupBy("customer_id", "country")
          .agg(F.count("*").alias("cnt"))
          .withColumn(
              "rank",
              F.rank().over(
                  Window.partitionBy("customer_id").orderBy(F.col("cnt").desc())
              )
          )
          .filter(F.col("rank") == 1)
          .select("customer_id", "country")
    )

    # Favourite category per customer (by revenue)
    favourite_category = (
        tx.groupBy("customer_id", "stock_code")
          .agg(F.sum("line_total").alias("category_revenue"))
          .join(
              dlt.read("products").select("stock_code", "category"),
              on="stock_code", how="left"
          )
          .groupBy("customer_id")
          .agg(
              F.first(
                  F.col("category"),
                  ignorenulls=True
              ).alias("favourite_category")
          )
    )

    # ---------------------------------------------------------------------------
    # RFM scoring (quintile-based, 1-5)
    # ---------------------------------------------------------------------------
    rfm_scored = (
        rfm
            .withColumn(
                "rfm_recency_score",
                F.ntile(5).over(
                    Window.orderBy(F.col("days_since_last_purchase").desc())
                )
            )
            .withColumn(
                "rfm_frequency_score",
                F.ntile(5).over(
                    Window.orderBy(F.col("total_orders"))
                )
            )
            .withColumn(
                "rfm_monetary_score",
                F.ntile(5).over(
                    Window.orderBy(F.col("total_revenue_lifetime"))
                )
            )
    )

    # ---------------------------------------------------------------------------
    # Join everything together
    # ---------------------------------------------------------------------------
    base = (
        customers
            .join(rfm_scored,       on="customer_id", how="left")
            .join(favourite_category, on="customer_id", how="left")
            .join(customer_country,  on="customer_id", how="left")
            .select(
                "customer_id",
                "full_name",
                "loyalty_tier",
                "total_revenue_lifetime",
                "total_orders",
                "avg_order_value",
                "days_since_last_purchase",
                "days_since_first_purchase",
                "favourite_category",
                "country",           # derived from transactions join above
                "rfm_recency_score",
                "rfm_frequency_score",
                "rfm_monetary_score",
                # ML writeback columns — populated after the ML job runs
                # Initial value is null; updated via MERGE in segmentation.py
                F.lit(None).cast("string").alias("customer_segment"),
                F.lit(None).cast("float").alias("churn_risk_score"),
            )
            .withColumn("_rebuilt_at", F.current_timestamp())
    )

    return base
