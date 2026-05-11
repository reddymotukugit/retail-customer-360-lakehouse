"""
load_sqlserver.py
-----------------
Loads all four CSV files from data/raw/ into a local SQL Server 2022 Express
database called RetailDB.

Creates the database and tables if they don't exist, then bulk-inserts
using pandas + pyodbc with fast_executemany=True for performance.

Usage:
    pip install pandas pyodbc sqlalchemy
    python data/setup/load_sqlserver.py

Prerequisites:
    1. SQL Server 2022 Express installed and running
    2. SQL Server Authentication enabled
    3. TCP/IP enabled in SQL Server Configuration Manager
    4. All four CSVs exist in data/raw/ (run fetch and generate scripts first)

Environment variables (or edit CONFIG below):
    SQL_SERVER    -- hostname or IP  (default: localhost)
    SQL_USER      -- SQL login       (default: sa)
    SQL_PASSWORD  -- SA password     (required — set via env var, never hardcode)
    SQL_PORT      -- TCP port        (default: 1433)
"""

import os
import sys
import pandas as pd
import pyodbc
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# Configuration — override via environment variables
# ---------------------------------------------------------------------------
CONFIG = {
    "server": os.getenv("SQL_SERVER", "localhost"),
    "port": int(os.getenv("SQL_PORT", "1433")),
    "user": os.getenv("SQL_USER", "sa"),
    "password": os.getenv("SQL_PASSWORD", ""),  # ALWAYS set via env var
    "database": "RetailDB",
}

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")

# ---------------------------------------------------------------------------
# DDL — table definitions
# ---------------------------------------------------------------------------
DDL = {
    "transactions": """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='transactions' AND xtype='U')
        CREATE TABLE dbo.transactions (
            invoice_no      NVARCHAR(20)    NOT NULL,
            stock_code      NVARCHAR(20)    NOT NULL,
            description     NVARCHAR(255)   NULL,
            quantity        INT             NOT NULL,
            invoice_date    DATETIME2       NOT NULL,
            unit_price      DECIMAL(10,2)   NOT NULL,
            customer_id     INT             NULL,
            country         NVARCHAR(100)   NULL,
            CONSTRAINT PK_transactions PRIMARY KEY (invoice_no, stock_code)
        );
    """,
    "customers": """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='customers' AND xtype='U')
        CREATE TABLE dbo.customers (
            customer_id         INT             NOT NULL PRIMARY KEY,
            full_name           NVARCHAR(150)   NULL,
            email               NVARCHAR(255)   NULL,
            phone               NVARCHAR(50)    NULL,
            date_of_birth       DATE            NULL,
            registration_date   DATE            NULL,
            loyalty_tier        NVARCHAR(20)    NULL,
            is_wholesaler       BIT             NULL,
            preferred_store_id  NVARCHAR(20)    NULL,
            marketing_opt_in    BIT             NULL
        );
    """,
    "products": """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='products' AND xtype='U')
        CREATE TABLE dbo.products (
            stock_code          NVARCHAR(20)    NOT NULL PRIMARY KEY,
            description         NVARCHAR(255)   NULL,
            category            NVARCHAR(100)   NULL,
            avg_unit_price      DECIMAL(10,2)   NULL,
            cost_price          DECIMAL(10,2)   NULL,
            weight_grams        INT             NULL,
            is_active           BIT             NULL,
            supplier_id         NVARCHAR(20)    NULL,
            first_listed_date   DATE            NULL
        );
    """,
    "stores": """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='stores' AND xtype='U')
        CREATE TABLE dbo.stores (
            store_id        NVARCHAR(20)    NOT NULL PRIMARY KEY,
            store_name      NVARCHAR(255)   NULL,
            country         NVARCHAR(100)   NULL,
            region          NVARCHAR(50)    NULL,
            timezone        NVARCHAR(50)    NULL,
            currency_code   NCHAR(3)        NULL,
            is_active       BIT             NULL,
            opened_date     DATE            NULL
        );
    """,
    # Watermark table for ADF incremental load pattern
    "pipeline_watermarks": """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='pipeline_watermarks' AND xtype='U')
        CREATE TABLE dbo.pipeline_watermarks (
            pipeline_name       NVARCHAR(100)   NOT NULL PRIMARY KEY,
            last_watermark_value DATETIME2      NOT NULL
        );

        IF NOT EXISTS (SELECT 1 FROM dbo.pipeline_watermarks WHERE pipeline_name = 'pl_ingest_transactions')
        INSERT INTO dbo.pipeline_watermarks (pipeline_name, last_watermark_value)
        VALUES ('pl_ingest_transactions', '1900-01-01 00:00:00');
    """,
}


def get_connection_string() -> str:
    if not CONFIG["password"]:
        print("ERROR: SQL_PASSWORD environment variable is not set.")
        print("Set it before running: export SQL_PASSWORD='YourPassword'")
        sys.exit(1)

    driver = "ODBC Driver 18 for SQL Server"
    # Fall back to Driver 17 if 18 not available
    available = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if available:
        driver = sorted(available, reverse=True)[0]
    print(f"Using ODBC driver: {driver}")

    return (
        f"mssql+pyodbc://{CONFIG['user']}:{quote_plus(CONFIG['password'])}"
        f"@{CONFIG['server']}:{CONFIG['port']}/{CONFIG['database']}"
        f"?driver={quote_plus(driver)}&TrustServerCertificate=yes&Encrypt=no&Connection+Timeout=30"
    )


def ensure_database_exists():
    """Connect to master and create RetailDB if it doesn't exist."""
    driver = sorted([d for d in pyodbc.drivers() if "SQL Server" in d], reverse=True)[0]
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={CONFIG['server']},{CONFIG['port']};"
        f"DATABASE=master;"
        f"UID={CONFIG['user']};"
        f"PWD={CONFIG['password']};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
        f"Connection Timeout=30;"
    )
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()
    cursor.execute(
        f"IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = '{CONFIG['database']}')"
        f" CREATE DATABASE [{CONFIG['database']}]"
    )
    conn.close()
    print(f"Database '{CONFIG['database']}' is ready.")


def create_tables(engine):
    with engine.connect() as conn:
        for table_name, ddl in DDL.items():
            conn.execute(text(ddl))
            conn.commit()
            print(f"  Table '{table_name}' is ready.")


def load_table(engine, csv_file: str, table_name: str, dtype_map: dict = None, chunk_size: int = 10_000):
    path = os.path.join(RAW_DIR, csv_file)
    if not os.path.exists(path):
        print(f"  SKIP: {path} not found.")
        return

    print(f"\nLoading {csv_file} → dbo.{table_name}")

    # Truncate before reload for idempotency
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE TABLE dbo.{table_name}"))
        conn.commit()

    df = pd.read_csv(path, dtype=dtype_map)

    # Normalise string PK columns to UPPERCASE so case-insensitive SQL Server
    # collation (CI_AS) and pandas drop_duplicates agree on uniqueness.
    str_pk_cols = ["invoice_no", "stock_code", "store_id", "pipeline_name"]
    for col in str_pk_cols:
        if col in df.columns:
            df[col] = df[col].str.strip().str.upper()

    # Deduplicate on primary key columns to avoid SQL Server PK violations.
    # The UCI dataset contains real duplicate (invoice_no, stock_code) pairs.
    pk_cols = {
        "transactions":        ["invoice_no", "stock_code"],
        "customers":           ["customer_id"],
        "products":            ["stock_code"],
        "stores":              ["store_id"],
        "pipeline_watermarks": ["pipeline_name"],
    }
    if table_name in pk_cols:
        before = len(df)
        df = df.drop_duplicates(subset=pk_cols[table_name], keep="last")
        dropped = before - len(df)
        if dropped:
            print(f"  Deduplicated {dropped:,} rows on {pk_cols[table_name]}")

    # Write in chunks for better memory management
    total = 0
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i : i + chunk_size]
        chunk.to_sql(
            table_name,
            engine,
            schema="dbo",
            if_exists="append",
            index=False,
        )
        total += len(chunk)
        print(f"  {total:,} / {len(df):,} rows loaded...", end="\r")

    print(f"  ✓ {len(df):,} rows loaded into dbo.{table_name}     ")


def verify_counts(engine):
    tables = ["transactions", "customers", "products", "stores", "pipeline_watermarks"]
    print("\nRow counts in SQL Server:")
    with engine.connect() as conn:
        for t in tables:
            result = conn.execute(text(f"SELECT COUNT(*) FROM dbo.{t}"))
            count = result.scalar()
            print(f"  dbo.{t:<25} {count:>10,} rows")


def main():
    print("=== Retail Lakehouse — SQL Server Loader ===\n")

    ensure_database_exists()
    engine = create_engine(get_connection_string(), fast_executemany=True)

    print("\nCreating tables...")
    create_tables(engine)

    load_table(
        engine,
        "transactions.csv",
        "transactions",
        dtype_map={"invoice_no": str, "stock_code": str, "description": str, "country": str},
    )
    load_table(
        engine,
        "customers.csv",
        "customers",
        dtype_map={"customer_id": "Int64", "email": str, "loyalty_tier": str},
    )
    load_table(
        engine,
        "products.csv",
        "products",
        dtype_map={"stock_code": str, "description": str, "category": str},
    )
    load_table(
        engine,
        "stores.csv",
        "stores",
        dtype_map={"store_id": str, "country": str, "region": str},
    )

    verify_counts(engine)

    print(
        "\nAll tables loaded. Open SSMS and run:"
        "\n  SELECT TOP 10 * FROM dbo.transactions ORDER BY invoice_date DESC"
        "\nto verify the data looks correct.\n"
    )


if __name__ == "__main__":
    main()
