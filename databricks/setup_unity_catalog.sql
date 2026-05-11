-- =============================================================================
-- Unity Catalog Setup — Retail Lakehouse
-- =============================================================================
-- Run this in a Databricks SQL Warehouse or notebook if setup_databricks.sh
-- has already created the catalog and schemas via the REST API.
-- This file documents the DDL for reference / manual repair.
--
-- Workspace: https://adb-7405615013053011.11.azuredatabricks.net
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Catalog
-- ---------------------------------------------------------------------------
CREATE CATALOG IF NOT EXISTS retail_prod
  COMMENT 'Retail Customer 360 & Demand Forecasting Lakehouse';

-- ---------------------------------------------------------------------------
-- Schemas (layers)
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS retail_prod.bronze
  COMMENT 'Raw ingestion layer — Parquet files from ADLS via Auto Loader';

CREATE SCHEMA IF NOT EXISTS retail_prod.silver
  COMMENT 'Cleaned, validated Delta tables — DLT expectations applied';

CREATE SCHEMA IF NOT EXISTS retail_prod.gold
  COMMENT 'Business-ready aggregations — Customer 360, Daily KPIs, Demand Forecast';

CREATE SCHEMA IF NOT EXISTS retail_prod.ml
  COMMENT 'MLflow registered models — segmentation and demand forecasting';

-- ---------------------------------------------------------------------------
-- Grant workspace users read access on gold (for Power BI)
-- ---------------------------------------------------------------------------
-- Replace <your-powerbi-spn-or-user> with the Power BI service principal or user.
-- GRANT SELECT ON SCHEMA retail_prod.gold TO `<your-powerbi-spn-or-user>`;

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
SHOW SCHEMAS IN retail_prod;

-- Expected output:
--   bronze
--   gold
--   information_schema
--   ml
--   silver
