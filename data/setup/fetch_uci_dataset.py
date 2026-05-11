"""
fetch_uci_dataset.py
--------------------
Downloads the UCI Online Retail II dataset directly from the UCI archive
and saves it as a CSV in data/raw/.

The dataset ships as an xlsx with two sheets:
  - Year 2009-2010
  - Year 2010-2011

Both sheets are combined into a single transactions.csv.

Usage:
    pip3 install pandas openpyxl requests
    python3 data/setup/fetch_uci_dataset.py
"""

import io
import os
import zipfile

import pandas as pd
import requests

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")
DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"


def download_and_extract() -> pd.DataFrame:
    os.makedirs(RAW_DIR, exist_ok=True)

    print(f"Downloading UCI Online Retail II dataset...")
    print(f"URL: {DATASET_URL}\n")

    response = requests.get(DATASET_URL, stream=True, timeout=120)
    response.raise_for_status()

    total = int(response.headers.get("content-length", 0))
    downloaded = 0
    chunks = []
    for chunk in response.iter_content(chunk_size=65536):
        chunks.append(chunk)
        downloaded += len(chunk)
        if total:
            pct = downloaded / total * 100
            print(f"  {downloaded/1e6:.1f} / {total/1e6:.1f} MB ({pct:.0f}%)", end="\r")
    print(f"\nDownload complete: {downloaded/1e6:.1f} MB")

    raw_bytes = b"".join(chunks)

    print("Extracting xlsx from zip...")
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        # Find the xlsx file inside the zip
        xlsx_names = [n for n in zf.namelist() if n.endswith(".xlsx")]
        if not xlsx_names:
            raise FileNotFoundError(f"No .xlsx found in zip. Contents: {zf.namelist()}")
        xlsx_name = xlsx_names[0]
        print(f"  Found: {xlsx_name}")
        xlsx_bytes = zf.read(xlsx_name)

    print("Reading xlsx sheets (this takes ~30 seconds)...")
    xl = pd.ExcelFile(io.BytesIO(xlsx_bytes), engine="openpyxl")
    print(f"  Sheets: {xl.sheet_names}")

    dfs = []
    for sheet in xl.sheet_names:
        print(f"  Reading sheet: {sheet}")
        df = xl.parse(sheet)
        df["_sheet"] = sheet
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    print(f"\nCombined: {len(combined):,} rows, {combined.shape[1]} columns")
    print(f"Columns: {list(combined.columns)}")
    return combined


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    # Rename columns to snake_case
    col_map = {
        "Invoice":     "invoice_no",
        "StockCode":   "stock_code",
        "Description": "description",
        "Quantity":    "quantity",
        "InvoiceDate": "invoice_date",
        "Price":       "unit_price",
        "Customer ID": "customer_id",
        "CustomerID":  "customer_id",
        "Country":     "country",
    }
    df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
    df = df.drop(columns=["_sheet"], errors="ignore")

    # Type coercion
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    df["quantity"]     = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"]   = pd.to_numeric(df["unit_price"], errors="coerce")
    df["customer_id"]  = pd.to_numeric(df["customer_id"], errors="coerce").astype("Int64")

    # Drop rows with no invoice_date or stock_code
    df = df.dropna(subset=["invoice_date", "stock_code"])

    return df


def main():
    df_raw = download_and_extract()
    df     = normalise(df_raw)

    output_path = os.path.join(RAW_DIR, "transactions.csv")
    df.to_csv(output_path, index=False)

    print(f"\nSaved {len(df):,} rows to {output_path}")
    print(f"Date range        : {df['invoice_date'].min()} -> {df['invoice_date'].max()}")
    print(f"Unique customers  : {df['customer_id'].nunique():,}")
    print(f"Unique SKUs       : {df['stock_code'].nunique():,}")
    print(f"Unique countries  : {df['country'].nunique():,}")
    print(f"Cancellations     : {df['invoice_no'].astype(str).str.startswith('C').sum():,} rows")
    print("\nDone. Run generate_synthetic_tables.py next.")


if __name__ == "__main__":
    main()
