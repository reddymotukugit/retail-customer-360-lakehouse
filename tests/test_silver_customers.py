"""
test_silver_customers.py
-------------------------
Unit tests for Silver customers transformation logic.
"""

import pytest
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType,
    DateType, BooleanType
)
from datetime import date


@pytest.fixture(scope="session")
def spark():
    return (
        SparkSession.builder
            .master("local[1]")
            .appName("test_silver_customers")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
    )


@pytest.fixture
def sample_customers(spark):
    schema = StructType([
        StructField("customer_id",        LongType(),    False),
        StructField("full_name",          StringType(),  True),
        StructField("email",              StringType(),  True),
        StructField("loyalty_tier",       StringType(),  True),
        StructField("is_wholesaler",      BooleanType(), True),
        StructField("marketing_opt_in",   BooleanType(), True),
        StructField("registration_date",  DateType(),    True),
    ])

    data = [
        # Valid customer
        (17850, "Alice Smith",  "alice@gmail.com",       "gold",     False, True,  date(2015, 3, 10)),
        # Email with uppercase — should be lowercased
        (17851, "Bob Jones",    "BOB.JONES@YAHOO.COM",   "Silver",   False, True,  date(2016, 6, 1)),
        # Invalid email — should be quarantined
        (17852, "Carol White",  "not-an-email",          "Bronze",   False, False, date(2017, 1, 1)),
        # Null email — should be quarantined
        (17853, "Dave Brown",   None,                    "Platinum", True,  True,  date(2018, 4, 20)),
        # Invalid loyalty tier — should be dropped
        (17854, "Eve Green",    "eve@outlook.com",       "Diamond",  False, True,  date(2019, 2, 1)),
        # Duplicate customer_id — keep only one
        (17850, "Alice Smith",  "alice@gmail.com",       "gold",     False, True,  date(2015, 3, 10)),
    ]

    return spark.createDataFrame(data, schema=schema)


EMAIL_PATTERN = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
VALID_TIERS = ["Bronze", "Silver", "Gold", "Platinum"]


def apply_silver_customer_logic(df):
    return (
        df
            .filter(F.col("email").rlike(EMAIL_PATTERN))
            .filter(F.col("customer_id").isNotNull())
            .filter(F.initcap(F.col("loyalty_tier")).isin(VALID_TIERS))
            .withColumn("email", F.lower(F.trim(F.col("email"))))
            .withColumn("full_name", F.trim(F.col("full_name")))
            .withColumn("loyalty_tier", F.initcap(F.trim(F.col("loyalty_tier"))))
            .dropDuplicates(["customer_id"])
    )


class TestSilverCustomers:

    def test_email_lowercased(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        bob = result.filter(F.col("customer_id") == 17851).collect()
        assert len(bob) == 1
        assert bob[0].email == "bob.jones@yahoo.com", "Email must be lowercased"

    def test_invalid_email_excluded(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        carol = result.filter(F.col("customer_id") == 17852).collect()
        assert len(carol) == 0, "Customer with invalid email must be excluded"

    def test_null_email_excluded(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        dave = result.filter(F.col("customer_id") == 17853).collect()
        assert len(dave) == 0, "Customer with null email must be excluded"

    def test_invalid_loyalty_tier_excluded(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        eve = result.filter(F.col("customer_id") == 17854).collect()
        assert len(eve) == 0, "Customer with invalid loyalty_tier must be excluded"

    def test_loyalty_tier_normalised(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        alice = result.filter(F.col("customer_id") == 17850).collect()
        assert len(alice) == 1
        assert alice[0].loyalty_tier == "Gold", "loyalty_tier must be title-cased"

    def test_deduplication(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        alice_count = result.filter(F.col("customer_id") == 17850).count()
        assert alice_count == 1, "Duplicate customer_id must be deduplicated"

    def test_valid_customers_survive(self, sample_customers):
        result = apply_silver_customer_logic(sample_customers)
        # alice (17850) and bob (17851) should survive
        ids = {r.customer_id for r in result.collect()}
        assert 17850 in ids and 17851 in ids, "Valid customers must survive"
