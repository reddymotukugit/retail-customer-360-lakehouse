# Databricks notebook source
# Bronze Layer — Auto Loader Ingestion
# =====================================
# Watches three ADLS Gen2 paths using Structured Streaming + Auto Loader.
# Uses directory listing mode (no Event Grid required).
#
# Schema is EXPLICIT — never inferred. Catches upstream type changes at ingestion.
# Unity Catalog namespace: retail_prod.bronze.*

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField,
    StringType, IntegerType, LongType,
    DecimalType, TimestampType, DateType, BooleanType
)

# ---------------------------------------------------------------------------
# Explicit schemas — never use schema inference in production
# ---------------------------------------------------------------------------

TRANSACTIONS_SCHEMA = StructType([
    StructField("invoice_no",   StringType(),       nullable=False),
    StructField("stock_code",   StringType(),       nullable=False),
    StructField("description",  StringType(),       nullable=True),
    StructField("quantity",     IntegerType(),      nullable=False),
    StructField("invoice_date", TimestampType(),    nullable=False),
    StructField("unit_price",   DecimalType(10, 2), nullable=False),
    StructField("customer_id",  LongType(),         nullable=True),
    StructField("country",      StringType(),       nullable=True),
])

CUSTOMERS_SCHEMA = StructType([
    StructField("customer_id",        LongType(),    nullable=False),
    StructField("full_name",          StringType(),  nullable=True),
    StructField("email",              StringType(),  nullable=True),
    StructField("phone",              StringType(),  nullable=True),
    StructField("date_of_birth",      DateType(),    nullable=True),
    StructField("registration_date",  DateType(),    nullable=True),
    StructField("loyalty_tier",       StringType(),  nullable=True),
    StructField("is_wholesaler",      BooleanType(), nullable=True),
    StructField("preferred_store_id", StringType(),  nullable=True),
    StructField("marketing_opt_in",   BooleanType(), nullable=True),
])

PRODUCTS_SCHEMA = StructType([
    StructField("stock_code",        StringType(),      nullable=False),
    StructField("description",       StringType(),      nullable=True),
    StructField("category",          StringType(),      nullable=True),
    StructField("avg_unit_price",    DecimalType(10,2), nullable=True),
    StructField("cost_price",        DecimalType(10,2), nullable=True),
    StructField("weight_grams",      IntegerType(),     nullable=True),
    StructField("is_active",         BooleanType(),     nullable=True),
    StructField("supplier_id",       StringType(),      nullable=True),
    StructField("first_listed_date", DateType(),        nullable=True),
])

# ---------------------------------------------------------------------------
# Bronze streaming tables — append-only, never overwrite
# ---------------------------------------------------------------------------

@dlt.table(
    name="raw_transactions",
    comment="Append-only raw transaction log ingested from ADLS bronze/transactions/ via Auto Loader.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "bronze",
    }
)
def raw_transactions():
    storage_account = spark.conf.get("pipeline.storage_account", "stretaillhdev")
    bronze_base     = f"abfss://bronze@{storage_account}.dfs.core.windows.net"
    return (
        spark.readStream
            .format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.useNotifications", "false")   # directory listing — no Event Grid needed
            .option("cloudFiles.schemaEvolutionMode", "none")
            .schema(TRANSACTIONS_SCHEMA)
            .load(f"{bronze_base}/transactions/")
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.col("_metadata.file_path"))
    )


@dlt.table(
    name="raw_customers",
    comment="Full daily snapshot of customer profiles from ADLS bronze/customers/.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "bronze",
    }
)
def raw_customers():
    storage_account = spark.conf.get("pipeline.storage_account", "stretaillhdev")
    bronze_base     = f"abfss://bronze@{storage_account}.dfs.core.windows.net"
    return (
        spark.readStream
            .format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.useNotifications", "false")
            .option("cloudFiles.schemaEvolutionMode", "none")
            .schema(CUSTOMERS_SCHEMA)
            .load(f"{bronze_base}/customers/")
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.col("_metadata.file_path"))
    )


@dlt.table(
    name="raw_products",
    comment="Full daily snapshot of product catalogue from ADLS bronze/products/.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "quality": "bronze",
    }
)
def raw_products():
    storage_account = spark.conf.get("pipeline.storage_account", "stretaillhdev")
    bronze_base     = f"abfss://bronze@{storage_account}.dfs.core.windows.net"
    return (
        spark.readStream
            .format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.useNotifications", "false")
            .option("cloudFiles.schemaEvolutionMode", "none")
            .schema(PRODUCTS_SCHEMA)
            .load(f"{bronze_base}/products/")
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.col("_metadata.file_path"))
    )
