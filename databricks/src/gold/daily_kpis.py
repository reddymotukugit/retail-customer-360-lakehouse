# Databricks notebook source
# Gold Layer — Daily KPIs
# ========================
# One row per calendar date. This is the table Power BI is built on.
# Rebuilt daily by the Lakeflow pipeline.
#
# Columns:
#   report_date, total_revenue, total_orders, unique_customers,
#   avg_basket_value, new_customers, returning_customers,
#   cancellation_rate, top_category_by_revenue,
#   total_units_sold, avg_unit_price
#
# Unity Catalog namespace: retail_prod.gold.daily_kpis

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType
from pyspark.sql.window import Window

@dlt.table(
    name="gold.daily_kpis",
    comment="One row per calendar date. Powers the Power BI dashboard.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "gold",
    }
)
def daily_kpis():
    tx = dlt.read("transactions")
    cancelled = dlt.read("cancelled_transactions")

    # Daily revenue, orders, customers
    daily_sales = (
        tx.groupBy(F.to_date("invoice_date").alias("report_date"))
          .agg(
              F.sum("line_total").cast(DecimalType(14, 2)).alias("total_revenue"),
              F.countDistinct("invoice_no").alias("total_orders"),
              F.countDistinct("customer_id").alias("unique_customers"),
              F.sum("quantity").alias("total_units_sold"),
              F.avg("unit_price").cast(DecimalType(10, 2)).alias("avg_unit_price"),
          )
          .withColumn(
              "avg_basket_value",
              (F.col("total_revenue") / F.col("total_orders")).cast(DecimalType(10, 2))
          )
    )

    # New vs returning customers (first purchase date comparison)
    first_purchase = (
        tx.groupBy("customer_id")
          .agg(F.to_date(F.min("invoice_date")).alias("first_purchase_date"))
    )

    daily_new = (
        tx.join(first_purchase, on="customer_id", how="left")
          .withColumn("report_date", F.to_date("invoice_date"))
          .withColumn(
              "is_new",
              F.col("report_date") == F.col("first_purchase_date")
          )
          .groupBy("report_date")
          .agg(
              F.countDistinct(
                  F.when(F.col("is_new"), F.col("customer_id"))
              ).alias("new_customers"),
              F.countDistinct(
                  F.when(~F.col("is_new"), F.col("customer_id"))
              ).alias("returning_customers"),
          )
    )

    # Cancellation rate — cancelled invoices / total invoices per day
    daily_cancellations = (
        cancelled.groupBy(F.to_date("invoice_date").alias("report_date"))
                 .agg(F.countDistinct("invoice_no").alias("cancelled_orders"))
    )

    # Top category by revenue per day
    products = dlt.read("products").select("stock_code", "category")
    top_category = (
        tx.join(products, on="stock_code", how="left")
          .groupBy(F.to_date("invoice_date").alias("report_date"), "category")
          .agg(F.sum("line_total").alias("cat_revenue"))
          .withColumn(
              "rank",
              F.rank().over(
                  Window.partitionBy("report_date").orderBy(F.col("cat_revenue").desc())
              )
          )
          .filter(F.col("rank") == 1)
          .select("report_date", F.col("category").alias("top_category_by_revenue"))
    )

    # Join everything
    result = (
        daily_sales
            .join(daily_new, on="report_date", how="left")
            .join(daily_cancellations, on="report_date", how="left")
            .join(top_category, on="report_date", how="left")
            .withColumn(
                "cancellation_rate",
                F.when(
                    F.col("total_orders") > 0,
                    (F.col("cancelled_orders") / F.col("total_orders")).cast(DecimalType(5, 4))
                ).otherwise(F.lit(0.0))
            )
            .fillna(0, subset=["new_customers", "returning_customers", "cancelled_orders"])
            .withColumn("_rebuilt_at", F.current_timestamp())
            .orderBy("report_date")
    )

    return result
