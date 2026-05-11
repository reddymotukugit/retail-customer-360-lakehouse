# Databricks notebook source
# Gold Layer — Demand Forecast Table
# =====================================
# This table is WRITTEN by the ML job (demand_forecast.py), not by the Lakeflow pipeline.
# This file defines the target schema and creates the table if it doesn't exist.
# Registered in Unity Catalog.
#
# Written by: ml/demand_forecast.py (weekly retrain job)
#
# Columns:
#   stock_code, forecast_date, predicted_units, lower_bound_80, upper_bound_80,
#   model_version, run_id, generated_at
#
# Unity Catalog namespace: retail_prod.gold.demand_forecast

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

spark.sql("""
    CREATE TABLE IF NOT EXISTS retail_prod.gold.demand_forecast (
        stock_code      STRING          NOT NULL COMMENT 'SKU being forecast',
        forecast_date   DATE            NOT NULL COMMENT 'Calendar date of the forecast',
        predicted_units DOUBLE          COMMENT 'Point forecast: predicted units sold',
        lower_bound_80  DOUBLE          COMMENT '80% prediction interval lower bound',
        upper_bound_80  DOUBLE          COMMENT '80% prediction interval upper bound',
        model_version   STRING          COMMENT 'MLflow model version used to generate forecast',
        run_id          STRING          COMMENT 'MLflow run_id for traceability',
        generated_at    TIMESTAMP       COMMENT 'When this forecast row was written'
    )
    USING DELTA
    COMMENT 'Weekly SKU-level demand forecast from Prophet. Written by ML retrain job.'
    TBLPROPERTIES (
        'quality'                            = 'gold',
        'delta.autoOptimize.optimizeWrite'   = 'true'
    )
""")

print("retail_prod.gold.demand_forecast table is ready.")
