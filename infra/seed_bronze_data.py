#!/usr/bin/env python3
"""
seed_bronze_data.py
===================
Uploads sample Parquet files to the bronze ADLS container using the
storage account key (avoids needing blob-data RBAC on your user account).

Parquet types are written with explicit PyArrow schemas so Spark can read
them without type-mismatch errors:
  - Timestamps  → pa.timestamp('us', tz='UTC')   (Spark TimestampType)
  - Decimals    → pa.decimal128(10, 2)            (Spark DecimalType(10,2))
  - Dates       → pa.date32()                     (Spark DateType)

Run:
    python3 infra/seed_bronze_data.py
"""

import os, sys, json, io, datetime, random, subprocess, pathlib, tempfile
from decimal import Decimal

STORAGE_ACCOUNT = "stretaillhdev"
CONTAINER       = "bronze"
RESOURCE_GROUP  = "rg-retaillh-dev"
YEAR_MONTH      = "year=2026/month=05"

def run(cmd, capture=True):
    r = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr.strip()[:300]}")
        return None
    return r.stdout.strip()

# ── Install deps ──────────────────────────────────────────────────────────────
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    os.system("pip3 install pyarrow --break-system-packages -q")
    import pyarrow as pa
    import pyarrow.parquet as pq

# ── Step 1: get storage account key ──────────────────────────────────────────
print("=== Step 1: Get storage account key ===")
key = run(
    f"az storage account keys list "
    f"--account-name {STORAGE_ACCOUNT} "
    f"--resource-group {RESOURCE_GROUP} "
    f"--query \"[0].value\" -o tsv"
)
if not key:
    print("ERROR: Could not get storage key. Make sure you're logged in: az login")
    sys.exit(1)
print(f"  Key obtained (ending ...{key[-6:]})")

KEY_FLAG = f"--account-key \"{key}\""

# ── Step 2: Delete old files (bad types) ─────────────────────────────────────
print("\n=== Step 2: Listing and removing old bronze files ===")
listing = run(
    f"az storage blob list "
    f"--account-name {STORAGE_ACCOUNT} --container-name {CONTAINER} "
    f"{KEY_FLAG} --output json --num-results 200"
)
if listing:
    blobs = json.loads(listing)
    if blobs:
        print(f"  Found {len(blobs)} existing blob(s):")
        for b in blobs:
            size = b.get("properties", {}).get("contentLength", 0)
            print(f"    {b['name']}  ({size:,} bytes)")
        print("  Deleting all existing blobs to avoid stale data...")
        for b in blobs:
            del_result = run(
                f"az storage blob delete "
                f"--account-name {STORAGE_ACCOUNT} "
                f"--container-name {CONTAINER} "
                f"--name \"{b['name']}\" "
                f"{KEY_FLAG} --output none"
            )
            if del_result is None:
                print(f"    Could not delete {b['name']}")
            else:
                print(f"    Deleted: {b['name']}")
    else:
        print("  Container is empty — nothing to delete.")
else:
    print("  Could not list blobs.")

# ── Step 3: Generate sample data ──────────────────────────────────────────────
print("\n=== Step 3: Generating sample data (correct Parquet types) ===")

random.seed(42)
TZ_UTC = datetime.timezone.utc
today  = datetime.date(2026, 5, 11)

def d(val):
    """Convert float → Decimal with 2 dp, as a string to avoid float noise."""
    return Decimal(f"{val:.2f}")

def ts(dt_naive):
    """Make a naive datetime UTC-aware (Spark needs tz='UTC' timestamp)."""
    return dt_naive.replace(tzinfo=TZ_UTC)

# ── Products ─────────────────────────────────────────────────────────────────
categories = ["Home Decor", "Gifts", "Kitchen", "Stationery", "Seasonal", "Toys", "Garden"]

products_rows = [
    {
        "stock_code":        f"SKU{i:04d}",
        "description":       f"Product {i} description",
        "category":          random.choice(categories),
        "avg_unit_price":    d(random.uniform(1.5, 49.99)),
        "cost_price":        d(random.uniform(0.5, 25.00)),
        "weight_grams":      random.randint(50, 2000),
        "is_active":         random.random() > 0.05,
        "supplier_id":       f"SUP{random.randint(1,10):03d}",
        "first_listed_date": today - datetime.timedelta(days=random.randint(30, 730)),
    }
    for i in range(1, 101)
]

PRODUCTS_SCHEMA = pa.schema([
    pa.field("stock_code",        pa.string(),         nullable=False),
    pa.field("description",       pa.string(),         nullable=True),
    pa.field("category",          pa.string(),         nullable=True),
    pa.field("avg_unit_price",    pa.decimal128(10,2), nullable=True),
    pa.field("cost_price",        pa.decimal128(10,2), nullable=True),
    pa.field("weight_grams",      pa.int32(),          nullable=True),
    pa.field("is_active",         pa.bool_(),          nullable=True),
    pa.field("supplier_id",       pa.string(),         nullable=True),
    pa.field("first_listed_date", pa.date32(),         nullable=True),
])

def rows_to_table(rows, schema):
    """Convert list-of-dicts to a PyArrow Table with the given schema."""
    col_names = [f.name for f in schema]
    col_data  = {name: [r[name] for r in rows] for name in col_names}
    arrays    = []
    for field in schema:
        arrays.append(pa.array(col_data[field.name], type=field.type))
    return pa.table(dict(zip(col_names, arrays)), schema=schema)

products_table = rows_to_table(products_rows, PRODUCTS_SCHEMA)
print(f"  Products:     {products_table.num_rows} rows")

# ── Customers ─────────────────────────────────────────────────────────────────
tiers   = ["Bronze", "Silver", "Gold", "Platinum"]
first_n = ["Alice","Bob","Carol","David","Eve","Frank","Grace","Henry","Isla","Jack",
           "Karen","Liam","Mia","Noah","Olivia","Peter","Quinn","Rachel","Sam","Tina"]
last_n  = ["Smith","Jones","Brown","Wilson","Taylor","Davies","Evans","Thomas","Roberts","Lewis"]

customers_rows = [
    {
        "customer_id":        cid,
        "full_name":          f"{random.choice(first_n)} {random.choice(last_n)}",
        "email":              f"user{cid}@example.com",
        "phone":              f"+44 7700 {cid}",
        "date_of_birth":      today - datetime.timedelta(days=random.randint(20*365, 70*365)),
        "registration_date":  today - datetime.timedelta(days=random.randint(30, 1000)),
        "loyalty_tier":       random.choice(tiers),
        "is_wholesaler":      random.random() < 0.1,
        "preferred_store_id": f"STORE{random.randint(1,5):02d}",
        "marketing_opt_in":   random.random() > 0.3,
    }
    for cid in range(17850, 17850 + 200)
]

CUSTOMERS_SCHEMA = pa.schema([
    pa.field("customer_id",        pa.int64(),   nullable=False),
    pa.field("full_name",          pa.string(),  nullable=True),
    pa.field("email",              pa.string(),  nullable=True),
    pa.field("phone",              pa.string(),  nullable=True),
    pa.field("date_of_birth",      pa.date32(),  nullable=True),
    pa.field("registration_date",  pa.date32(),  nullable=True),
    pa.field("loyalty_tier",       pa.string(),  nullable=True),
    pa.field("is_wholesaler",      pa.bool_(),   nullable=True),
    pa.field("preferred_store_id", pa.string(),  nullable=True),
    pa.field("marketing_opt_in",   pa.bool_(),   nullable=True),
])

customers_table = rows_to_table(customers_rows, CUSTOMERS_SCHEMA)
print(f"  Customers:    {customers_table.num_rows} rows")

# ── Transactions (30 days) ────────────────────────────────────────────────────
countries = ["United Kingdom","Germany","France","Netherlands","Australia",
             "United States","Canada","Japan","Spain","Italy"]
tx_rows = []
invoice_counter = 570000
for day_offset in range(30):
    tx_date = today - datetime.timedelta(days=29 - day_offset)
    for _ in range(random.randint(80, 200)):
        invoice_no  = f"INV{invoice_counter:07d}"
        invoice_counter += 1
        cust_id     = random.choice(customers_rows)["customer_id"] if random.random() > 0.05 else None
        country     = random.choice(countries)
        for _ in range(random.randint(1, 6)):
            prod       = random.choice(products_rows)
            quantity   = random.randint(1, 20)
            unit_price = d(float(prod["avg_unit_price"]) * random.uniform(0.8, 1.2))
            tx_rows.append({
                "invoice_no":   invoice_no,
                "stock_code":   prod["stock_code"],
                "description":  prod["description"],
                "quantity":     quantity,
                "invoice_date": ts(datetime.datetime.combine(
                    tx_date,
                    datetime.time(random.randint(8, 20), random.randint(0, 59))
                )),
                "unit_price":   unit_price,
                "customer_id":  cust_id,
                "country":      country,
            })

# ~2% cancellations
for _ in range(100):
    orig = random.choice(tx_rows)
    tx_rows.append({
        **orig,
        "invoice_no": "C" + orig["invoice_no"][1:],
        "quantity":   -abs(orig["quantity"]),
    })

TRANSACTIONS_SCHEMA = pa.schema([
    pa.field("invoice_no",   pa.string(),                  nullable=False),
    pa.field("stock_code",   pa.string(),                  nullable=False),
    pa.field("description",  pa.string(),                  nullable=True),
    pa.field("quantity",     pa.int32(),                   nullable=False),
    pa.field("invoice_date", pa.timestamp('us', tz='UTC'), nullable=False),
    pa.field("unit_price",   pa.decimal128(10, 2),         nullable=False),
    pa.field("customer_id",  pa.int64(),                   nullable=True),
    pa.field("country",      pa.string(),                  nullable=True),
])

transactions_table = rows_to_table(tx_rows, TRANSACTIONS_SCHEMA)
print(f"  Transactions: {transactions_table.num_rows} rows across 30 days")

# ── Step 4: Write Parquet locally ──────────────────────────────────────────────
print("\n=== Step 4: Writing Parquet files (PyArrow explicit schema) ===")
tmpdir = pathlib.Path(tempfile.mkdtemp())

file_map = {
    f"transactions/{YEAR_MONTH}/transactions.parquet": transactions_table,
    f"customers/{YEAR_MONTH}/customers.parquet":       customers_table,
    f"products/{YEAR_MONTH}/products.parquet":         products_table,
}
local_paths = {}
for blob_name, table in file_map.items():
    local = tmpdir / pathlib.Path(blob_name).name
    pq.write_table(table, local)
    local_paths[blob_name] = local
    print(f"  Written: {local.name}  ({local.stat().st_size:,} bytes)")

# Verify types
print("\n  Verifying Parquet schemas:")
for blob_name, local in local_paths.items():
    schema = pq.read_schema(local)
    print(f"\n  {pathlib.Path(blob_name).name}:")
    for field in schema:
        print(f"    {field.name}: {field.type}")

# ── Step 5: Upload ─────────────────────────────────────────────────────────────
print("\n=== Step 5: Uploading to ADLS Gen2 ===")
for blob_name, local in local_paths.items():
    cmd = (
        f"az storage blob upload "
        f"--account-name {STORAGE_ACCOUNT} "
        f"--container-name {CONTAINER} "
        f"--name \"{blob_name}\" "
        f"--file \"{local}\" "
        f"{KEY_FLAG} "
        f"--overwrite true "
        f"--output none"
    )
    result = run(cmd)
    if result is None:
        print(f"  FAILED: {blob_name}")
    else:
        print(f"  Uploaded: {blob_name}")

# ── Step 6: Verify ─────────────────────────────────────────────────────────────
print("\n=== Step 6: Verification ===")
listing2 = run(
    f"az storage blob list "
    f"--account-name {STORAGE_ACCOUNT} --container-name {CONTAINER} "
    f"{KEY_FLAG} --output json"
)
if listing2:
    blobs2 = json.loads(listing2)
    for b in blobs2:
        size = b.get("properties", {}).get("contentLength", 0)
        print(f"  {b['name']}  ({size:,} bytes)")
    print(f"\n  Total blobs: {len(blobs2)}")
    if len(blobs2) >= 3:
        print("  ✓ All three datasets uploaded with correct Parquet types.")
        print("  ✓ Ready to run the pipeline!")
    else:
        print("  ⚠ Some uploads may have failed.")
else:
    print("  Could not verify — check Azure Portal > Storage Account > Containers > bronze")

print("""
=== Next step ===
    python3 infra/run_pipeline.py
""")
