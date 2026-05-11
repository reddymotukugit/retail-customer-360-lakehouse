"""
test_gold_kpis.py
------------------
Unit tests for the Gold daily_kpis aggregation logic.
"""

import pytest
from decimal import Decimal
from datetime import datetime, date
from pyspark.sql import SparkSession, functions as F, Window
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType,
    TimestampType, DecimalType, LongType
)


@pytest.fixture(scope="session")
def spark():
    return (
        SparkSession.builder
            .master("local[1]")
            .appName("test_gold_kpis")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
    )


@pytest.fixture
def sample_transactions(spark):
    schema = StructType([
        StructField("invoice_no",   StringType(),       False),
        StructField("stock_code",   StringType(),       False),
        StructField("quantity",     IntegerType(),      False),
        StructField("invoice_date", TimestampType(),    False),
        StructField("unit_price",   DecimalType(10, 2), False),
        StructField("line_total",   DecimalType(12, 2), False),
        StructField("customer_id",  LongType(),         False),
    ])

    data = [
        # Day 1 — 2 orders from 2 customers
        ("A001", "SKU1", 2, datetime(2010, 12, 1, 9, 0),  Decimal("5.00"), Decimal("10.00"), 1001),
        ("A002", "SKU2", 1, datetime(2010, 12, 1, 10, 0), Decimal("3.00"), Decimal("3.00"),  1002),
        # Day 2 — 1 order from customer 1001 (returning)
        ("A003", "SKU1", 3, datetime(2010, 12, 2, 9, 0),  Decimal("5.00"), Decimal("15.00"), 1001),
    ]

    return spark.createDataFrame(data, schema=schema)


def compute_daily_kpis(tx):
    daily_sales = (
        tx.groupBy(F.to_date("invoice_date").alias("report_date"))
          .agg(
              F.sum("line_total").cast(DecimalType(14, 2)).alias("total_revenue"),
              F.countDistinct("invoice_no").alias("total_orders"),
              F.countDistinct("customer_id").alias("unique_customers"),
              F.sum("quantity").alias("total_units_sold"),
          )
          .withColumn(
              "avg_basket_value",
              (F.col("total_revenue") / F.col("total_orders")).cast(DecimalType(10, 2))
          )
    )

    first_purchase = (
        tx.groupBy("customer_id")
          .agg(F.to_date(F.min("invoice_date")).alias("first_purchase_date"))
    )

    daily_new = (
        tx.join(first_purchase, on="customer_id", how="left")
          .withColumn("report_date", F.to_date("invoice_date"))
          .withColumn("is_new", F.col("report_date") == F.col("first_purchase_date"))
          .groupBy("report_date")
          .agg(
              F.countDistinct(F.when(F.col("is_new"), F.col("customer_id"))).alias("new_customers"),
              F.countDistinct(F.when(~F.col("is_new"), F.col("customer_id"))).alias("returning_customers"),
          )
    )

    return daily_sales.join(daily_new, on="report_date", how="left").orderBy("report_date")


class TestGoldKPIs:

    def test_row_count_per_day(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        assert result.count() == 2, "Should have one row per calendar day"

    def test_total_revenue_day1(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day1 = result.filter(F.col("report_date") == date(2010, 12, 1)).collect()[0]
        assert float(day1.total_revenue) == 13.00, f"Day 1 revenue should be 13.00, got {day1.total_revenue}"

    def test_total_orders_day1(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day1 = result.filter(F.col("report_date") == date(2010, 12, 1)).collect()[0]
        assert day1.total_orders == 2, f"Day 1 should have 2 orders, got {day1.total_orders}"

    def test_unique_customers_day1(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day1 = result.filter(F.col("report_date") == date(2010, 12, 1)).collect()[0]
        assert day1.unique_customers == 2, f"Day 1 should have 2 unique customers, got {day1.unique_customers}"

    def test_avg_basket_value_day1(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day1 = result.filter(F.col("report_date") == date(2010, 12, 1)).collect()[0]
        expected = round(13.0 / 2, 2)
        assert abs(float(day1.avg_basket_value) - expected) < 0.01, (
            f"avg_basket_value should be {expected}, got {day1.avg_basket_value}"
        )

    def test_new_customers_day1(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day1 = result.filter(F.col("report_date") == date(2010, 12, 1)).collect()[0]
        # Both customers 1001 and 1002 are new on day 1
        assert day1.new_customers == 2, f"Day 1 should have 2 new customers, got {day1.new_customers}"

    def test_returning_customers_day2(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        day2 = result.filter(F.col("report_date") == date(2010, 12, 2)).collect()[0]
        # Customer 1001 is returning on day 2 (first purchase was day 1)
        assert day2.returning_customers == 1, (
            f"Day 2 should have 1 returning customer, got {day2.returning_customers}"
        )

    def test_total_units_sold(self, sample_transactions):
        result = compute_daily_kpis(sample_transactions)
        total = result.agg(F.sum("total_units_sold")).collect()[0][0]
        assert total == 6, f"Total units across all days should be 6, got {total}"
