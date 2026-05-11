"""
test_silver_transactions.py
----------------------------
Unit tests for the Silver transactions transformation logic.
Tests run on a local PySpark session (no Databricks required).
"""

import pytest
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType,
    TimestampType, DecimalType, LongType
)


@pytest.fixture(scope="session")
def spark():
    return (
        SparkSession.builder
            .master("local[1]")
            .appName("test_silver_transactions")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
    )


@pytest.fixture
def sample_transactions(spark):
    schema = StructType([
        StructField("invoice_no",   StringType(),       False),
        StructField("stock_code",   StringType(),       False),
        StructField("description",  StringType(),       True),
        StructField("quantity",     IntegerType(),      False),
        StructField("invoice_date", TimestampType(),    False),
        StructField("unit_price",   DecimalType(10, 2), False),
        StructField("customer_id",  LongType(),         True),
        StructField("country",      StringType(),       True),
    ])

    data = [
        # Valid row
        ("536365", "85123A", "WHITE HANGING HEART",   6, datetime(2010, 12, 1, 8, 26), 2.55, 17850, "United Kingdom"),
        # Cancellation (invoice starts with C)
        ("C536391", "22556", "PLASTERS IN TIN SPACEBOY", -1, datetime(2010, 12, 1, 10, 3), 1.65, 17548, "United Kingdom"),
        # Null customer_id — should be quarantined
        ("536367", "84879",  "ASSORTED COLOUR BIRD",    32, datetime(2010, 12, 1, 8, 34), 1.69, None, "United Kingdom"),
        # Negative quantity (not a cancellation invoice) — should be dropped
        ("536368", "22960",  "JAM MAKING SET",          -6, datetime(2010, 12, 1, 8, 34), 0.85, 17548, "United Kingdom"),
        # Zero unit price — should be dropped
        ("536369", "21756",  "BATH BUILDING BLOCK WORD", 3, datetime(2010, 12, 1, 8, 35), 0.00, 13047, "United Kingdom"),
        # Duplicate row — same invoice_no + stock_code
        ("536365", "85123A", "WHITE HANGING HEART",   6, datetime(2010, 12, 1, 8, 26), 2.55, 17850, "United Kingdom"),
    ]

    return spark.createDataFrame(data, schema=schema)


def apply_silver_logic(df):
    """Replicate the Silver transactions transformation."""
    from decimal import Decimal

    result = (
        df
            .filter(~F.col("invoice_no").startswith("C"))
            .filter(F.col("customer_id").isNotNull())
            .filter(F.col("quantity") > 0)
            .filter(F.col("unit_price") >= 0)
            .filter(F.col("unit_price") > 0)   # unit_price = 0 also dropped
            .withColumn(
                "line_total",
                (F.col("quantity") * F.col("unit_price")).cast(DecimalType(12, 2))
            )
            .withColumn("invoice_year",  F.year("invoice_date"))
            .withColumn("invoice_month", F.month("invoice_date"))
            .dropDuplicates(["invoice_no", "stock_code"])
    )
    return result


class TestSilverTransactions:

    def test_cancellations_excluded(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        invoice_nos = [r.invoice_no for r in result.collect()]
        assert "C536391" not in invoice_nos, "Cancellation invoice must not appear in silver.transactions"

    def test_null_customer_excluded(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        customer_ids = [r.customer_id for r in result.collect()]
        assert None not in customer_ids, "Null customer_id rows must be excluded"

    def test_negative_quantity_excluded(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        quantities = [r.quantity for r in result.collect()]
        assert all(q > 0 for q in quantities), "Negative quantities must be dropped"

    def test_zero_unit_price_excluded(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        prices = [r.unit_price for r in result.collect()]
        assert all(float(p) > 0 for p in prices), "Zero unit_price rows must be dropped"

    def test_deduplication(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        # invoice 536365 + stock_code 85123A appears twice in input
        matching = result.filter(
            (F.col("invoice_no") == "536365") & (F.col("stock_code") == "85123A")
        ).count()
        assert matching == 1, "Duplicate (invoice_no, stock_code) pairs must be deduplicated"

    def test_line_total_computed(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        valid_row = result.filter(F.col("invoice_no") == "536365").collect()
        assert len(valid_row) == 1
        expected_line_total = round(6 * 2.55, 2)
        actual = float(valid_row[0].line_total)
        assert abs(actual - expected_line_total) < 0.01, (
            f"line_total should be {expected_line_total}, got {actual}"
        )

    def test_valid_row_survives(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        valid = result.filter(F.col("invoice_no") == "536365").collect()
        assert len(valid) == 1, "Valid row must survive all transformations"

    def test_output_row_count(self, sample_transactions):
        result = apply_silver_logic(sample_transactions)
        # Input: 6 rows
        # Excluded: C536391 (cancellation), 536367 (null customer),
        #           536368 (negative qty), 536369 (zero price), one duplicate of 536365
        # Expected: 1
        assert result.count() == 1, f"Expected 1 valid row, got {result.count()}"
