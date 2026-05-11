"""
generate_synthetic_tables.py
-----------------------------
Generates three synthetic lookup tables from the UCI transaction data:

  customers  -- one row per CustomerID (profile + loyalty info)
  products   -- one row per StockCode (catalogue metadata)
  stores     -- small country-level store/region lookup

These turn the flat transaction file into a proper relational schema
with four tables and real join keys.

Usage:
    pip install faker pandas
    python data/setup/generate_synthetic_tables.py

Prerequisites:
    data/raw/transactions.csv must exist (run fetch_uci_dataset.py first)

Output:
    data/raw/customers.csv
    data/raw/products.csv
    data/raw/stores.csv
"""

import os
import random
import pandas as pd
from faker import Faker

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")
SEED = 42
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

LOYALTY_TIERS = ["Bronze", "Silver", "Gold", "Platinum"]
LOYALTY_WEIGHTS = [0.45, 0.30, 0.18, 0.07]

PRODUCT_CATEGORIES = [
    "Gifts & Novelties",
    "Home Decor",
    "Kitchenware",
    "Stationery",
    "Seasonal",
    "Garden & Outdoor",
    "Toys & Games",
    "Textiles",
]

COUNTRY_STORE_MAP = {
    "United Kingdom": {"store_id": "UK-001", "region": "EMEA", "timezone": "Europe/London"},
    "Germany": {"store_id": "DE-001", "region": "EMEA", "timezone": "Europe/Berlin"},
    "France": {"store_id": "FR-001", "region": "EMEA", "timezone": "Europe/Paris"},
    "EIRE": {"store_id": "IE-001", "region": "EMEA", "timezone": "Europe/Dublin"},
    "Spain": {"store_id": "ES-001", "region": "EMEA", "timezone": "Europe/Madrid"},
    "Netherlands": {"store_id": "NL-001", "region": "EMEA", "timezone": "Europe/Amsterdam"},
    "Belgium": {"store_id": "BE-001", "region": "EMEA", "timezone": "Europe/Brussels"},
    "Switzerland": {"store_id": "CH-001", "region": "EMEA", "timezone": "Europe/Zurich"},
    "Australia": {"store_id": "AU-001", "region": "APAC", "timezone": "Australia/Sydney"},
    "Japan": {"store_id": "JP-001", "region": "APAC", "timezone": "Asia/Tokyo"},
    "USA": {"store_id": "US-001", "region": "Americas", "timezone": "America/New_York"},
    "Canada": {"store_id": "CA-001", "region": "Americas", "timezone": "America/Toronto"},
}
DEFAULT_STORE = {"store_id": "XX-001", "region": "Other", "timezone": "UTC"}


def load_transactions() -> pd.DataFrame:
    path = os.path.join(RAW_DIR, "transactions.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"transactions.csv not found at {path}.\n"
            "Run fetch_uci_dataset.py first."
        )
    return pd.read_csv(path, parse_dates=["invoice_date"])


def generate_customers(df: pd.DataFrame) -> pd.DataFrame:
    print("Generating customers table...")

    # Get all unique customer IDs that appear in transactions
    customer_ids = df["customer_id"].dropna().unique()
    customer_ids = sorted([int(c) for c in customer_ids])

    # Derive the preferred country per customer (most frequent)
    country_per_customer = (
        df.groupby("customer_id")["country"]
        .agg(lambda x: x.value_counts().index[0])
        .reset_index()
        .rename(columns={"country": "preferred_country"})
    )
    country_per_customer["customer_id"] = country_per_customer["customer_id"].astype(int)

    rows = []
    for cid in customer_ids:
        rows.append(
            {
                "customer_id": cid,
                "full_name": fake.name(),
                "email": f"customer{cid}@{fake.free_email_domain()}",
                "phone": fake.phone_number()[:20],
                "date_of_birth": fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat(),
                "registration_date": fake.date_between(
                    start_date="-8y", end_date="-1y"
                ).isoformat(),
                "loyalty_tier": random.choices(LOYALTY_TIERS, weights=LOYALTY_WEIGHTS, k=1)[0],
                "is_wholesaler": random.random() < 0.15,  # 15% are wholesalers (matches UCI context)
                "preferred_store_id": None,  # filled after merge
                "marketing_opt_in": random.random() < 0.68,
            }
        )

    customers = pd.DataFrame(rows)
    customers = customers.merge(country_per_customer, on="customer_id", how="left")

    # Map preferred store
    customers["preferred_store_id"] = customers["preferred_country"].map(
        lambda c: COUNTRY_STORE_MAP.get(c, DEFAULT_STORE)["store_id"]
    )
    customers.drop(columns=["preferred_country"], inplace=True)

    return customers


def generate_products(df: pd.DataFrame) -> pd.DataFrame:
    print("Generating products table...")

    # Get unique stock codes with their most common description
    product_base = (
        df[df["stock_code"].str.len() <= 10]  # filter out non-SKU codes
        .groupby("stock_code")
        .agg(
            description=("description", lambda x: x.dropna().value_counts().index[0] if len(x.dropna()) > 0 else ""),
            avg_unit_price=("unit_price", "mean"),
            first_seen=("invoice_date", "min"),
        )
        .reset_index()
    )

    rows = []
    for _, row in product_base.iterrows():
        random.seed(hash(row["stock_code"]) % (2**32))
        rows.append(
            {
                "stock_code": row["stock_code"],
                "description": row["description"],
                "category": random.choice(PRODUCT_CATEGORIES),
                "avg_unit_price": round(row["avg_unit_price"], 2),
                "cost_price": round(row["avg_unit_price"] * random.uniform(0.35, 0.65), 2),
                "weight_grams": random.randint(50, 2000),
                "is_active": True,
                "supplier_id": f"SUP-{random.randint(1, 25):03d}",
                "first_listed_date": row["first_seen"].date().isoformat()
                if pd.notna(row["first_seen"])
                else None,
            }
        )

    return pd.DataFrame(rows)


def generate_stores() -> pd.DataFrame:
    print("Generating stores table...")

    rows = []
    for country, info in COUNTRY_STORE_MAP.items():
        rows.append(
            {
                "store_id": info["store_id"],
                "store_name": f"{country} Online Store",
                "country": country,
                "region": info["region"],
                "timezone": info["timezone"],
                "currency_code": "GBP"
                if country in ["United Kingdom", "EIRE"]
                else (
                    "AUD"
                    if country == "Australia"
                    else ("JPY" if country == "Japan" else ("USD" if country in ["USA", "Canada"] else "EUR"))
                ),
                "is_active": True,
                "opened_date": fake.date_between(start_date="-15y", end_date="-5y").isoformat(),
            }
        )

    return pd.DataFrame(rows)


def main():
    os.makedirs(RAW_DIR, exist_ok=True)

    df = load_transactions()
    print(f"Loaded {len(df):,} transactions with {df['customer_id'].nunique():,} unique customers "
          f"and {df['stock_code'].nunique():,} unique SKUs.\n")

    customers = generate_customers(df)
    customers_path = os.path.join(RAW_DIR, "customers.csv")
    customers.to_csv(customers_path, index=False)
    print(f"  → Saved {len(customers):,} customers to {customers_path}")

    products = generate_products(df)
    products_path = os.path.join(RAW_DIR, "products.csv")
    products.to_csv(products_path, index=False)
    print(f"  → Saved {len(products):,} products to {products_path}")

    stores = generate_stores()
    stores_path = os.path.join(RAW_DIR, "stores.csv")
    stores.to_csv(stores_path, index=False)
    print(f"  → Saved {len(stores):,} stores to {stores_path}")

    print("\nSchema summary:")
    print(f"  transactions : {len(df):>8,} rows — invoice_no, stock_code, customer_id, ...")
    print(f"  customers    : {len(customers):>8,} rows — customer_id (PK), loyalty_tier, ...")
    print(f"  products     : {len(products):>8,} rows — stock_code (PK), category, ...")
    print(f"  stores       : {len(stores):>8,} rows — store_id (PK), country, region")
    print("\nDone. Run load_sqlserver.py next.")


if __name__ == "__main__":
    main()
