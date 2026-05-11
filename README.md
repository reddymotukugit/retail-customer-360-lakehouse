# Retail Customer 360 & Demand Forecasting Lakehouse

A production-grade Azure Data Engineering portfolio project demonstrating end-to-end lakehouse architecture — from on-premises SQL Server ingestion through ML-powered customer segmentation and demand forecasting, served via Power BI.

---

## Architecture

```
Local SQL Server 2022 Express
        │
        │  Self-Hosted Integration Runtime (SHIR)
        ▼
Azure Data Factory  ──────────────────────────────────────────────────────┐
  pl_ingest_transactions (watermark-based incremental)                    │
  pl_ingest_customers     (full daily)                                    │
  pl_ingest_products      (full daily)                                    │
        │                                                                 │
        │  Parquet → ADLS Gen2 bronze/                                   │
        ▼                                                                 │
Azure Databricks                                                          │
  Auto Loader (Bronze)  ── streaming ──► raw_transactions                 │
                                         raw_customers                    │
                                         raw_products                     │
        │                                                                 │
        │  Lakeflow Spark Declarative Pipelines                          │
        ▼                                                                 │
  Silver Layer                                                            │
    transactions          ← quality expectations, quarantine, line_total  │
    customers             ← email validation, SCD Type 1                  │
    products              ← slow mover flag, orphaned SKU flag            │
    cancelled_transactions                                                │
    _quarantine_transactions                                              │
    _quarantine_customers                                                 │
        │                                                                 │
        ▼                                                                 │
  Gold Layer                                                              │
    customer_360          ← RFM scores + ML segment writeback             │
    daily_kpis            ← Power BI source                               │
    demand_forecast       ← Prophet output                                │
        │                                                                 │
        │  MLflow Model Registry                                          │
        ▼                                                                 │
  ML Jobs (weekly)                                                        │
    K-Means RFM Segmentation  →  customer_360.customer_segment            │
    Prophet Demand Forecast   →  demand_forecast table                    │
    model_validation.py       →  Staging → Production gate                │
        │                                                                 │
        ▼                                                                 │
  Power BI  ──  Databricks SQL endpoint  ──  gold.daily_kpis             │
                                                                          │
  Unity Catalog (retail_prod)                                             │
    ├── bronze.*   (append-only, audit log)                               │
    ├── silver.*   (clean, validated)                                     │
    ├── gold.*     (business-ready)                                       │
    └── ml.*       (feature store, model artifacts)                       │
```

---

## Tech Stack

| Category | Tools |
|---|---|
| Data & Local | UCI Online Retail II, SQL Server 2022 Express, Python, ucimlrepo, Faker |
| Cloud Infra | Azure ADLS Gen2, Azure Data Factory, SHIR, Azure Key Vault, Terraform |
| Data Engineering | Azure Databricks (Premium), Spark, Auto Loader, Lakeflow SDP, Delta Lake, Unity Catalog |
| ML | MLflow, scikit-learn (K-Means), Prophet, Databricks Feature Store |
| DevOps | Declarative Automation Bundles, Databricks CLI, GitHub Actions |
| Serving | Databricks SQL, Power BI |
| Languages | Python, SQL, YAML, HCL, JSON, Parquet, Delta |

---

## Repository Structure

```
retail-lakehouse/
├── infra/                          # Terraform — Azure resources only
│   ├── main.tf                     # Resource Group, Databricks, cluster policy
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── storage/main.tf         # ADLS Gen2 + bronze/silver/gold containers
│       ├── adf/main.tf             # Data Factory + SHIR registration
│       └── keyvault/main.tf        # Secrets: SQL password + storage key
│
├── databricks/                     # Declarative Automation Bundle
│   ├── databricks.yml              # Bundle: targets dev + prod
│   ├── resources/                  # (job/pipeline YAML overrides if needed)
│   └── src/
│       ├── bronze/autoloader_ingest.py
│       ├── silver/transactions.py
│       ├── silver/customers.py
│       ├── silver/products.py
│       ├── gold/customer_360.py
│       ├── gold/daily_kpis.py
│       ├── gold/demand_forecast_table.py
│       └── ml/
│           ├── segmentation.py
│           ├── demand_forecast.py
│           └── model_validation.py
│
├── adf/                            # ADF pipeline JSON exports (version-controlled)
│   ├── pl_ingest_transactions.json
│   ├── pl_ingest_customers.json
│   ├── pl_ingest_products.json
│   └── linked_services/
│
├── data/setup/                     # Week 1 local setup scripts
│   ├── fetch_uci_dataset.py
│   ├── generate_synthetic_tables.py
│   └── load_sqlserver.py
│
├── tests/
│   ├── test_silver_transactions.py
│   ├── test_silver_customers.py
│   └── test_gold_kpis.py
│
└── .github/workflows/
    ├── terraform.yml               # PR → plan, merge → apply
    └── databricks_deploy.yml       # merge → validate → deploy → smoke test → promote
```

---

## Deployed Infrastructure

| Resource | Value |
|---|---|
| Resource Group | `rg-retaillh-dev` |
| ADLS Gen2 Storage Account | `stretaillhdev` |
| ADF Instance | `adf-retaillh-dev` |
| Key Vault | `kv-retaillh-dev` |
| Databricks Workspace | `adb-7405615013053011.11.azuredatabricks.net` |
| SQL Server VM (SHIR) | `20.62.125.63` |
| Cluster Policy ID | `00070BB969B7B0BF` |
| Subscription ID | `25089613-0f49-4b36-aeff-c96d9aa648c4` |

**ADF Pipeline Run IDs (initial bronze load — Succeeded):**
- `pl_ingest_customers`     → `2630dbd6-4cf8-11f1-9d3f-1238c3778c2f`  (37s)
- `pl_ingest_products`      → `2794e094-4cf8-11f1-9632-1238c3778c2f`  (36s)
- `pl_ingest_transactions`  → `28450c12-4cf8-11f1-b877-1238c3778c2f`  (94s, 1M+ rows)

---

## Build Order

### Week 1 — Local Environment ✅
```bash
pip install pandas faker pyodbc sqlalchemy openpyxl requests

# 1. Download UCI Online Retail II dataset (1,067,371 transactions)
python data/setup/fetch_uci_dataset.py

# 2. Generate synthetic customers, products, stores tables
python data/setup/generate_synthetic_tables.py
# Output: 5,942 customers | 5,121 products | 12 stores

# 3. Load into SQL Server (VM at 20.62.125.63)
export SQL_SERVER="20.62.125.63"
export SQL_PASSWORD='RetailLH@2026!'
python data/setup/load_sqlserver.py
# Output: 1,021,421 transactions loaded
```

### Week 2 — Azure Foundation (Terraform) ✅
```bash
cd infra
terraform init
terraform plan \
  -var="sql_server_password=RetailLH@2026!" \
  -var="sql_server_host=20.62.125.63"
terraform apply
# Provisions: ADLS Gen2, ADF, Key Vault, Databricks workspace, cluster policy
```
Install SHIR on the VM and register with the key from ADF Studio:
```powershell
# On the VM (20.62.125.63):
powershell -ExecutionPolicy Bypass -File infra/reinstall_shir.ps1
powershell -ExecutionPolicy Bypass -File infra/install_java.ps1
```

### Week 3 — ADF Pipelines ✅
```bash
cd retail-lakehouse
bash adf/deploy_adf.sh

# Trigger all three ingestion pipelines
az datafactory pipeline create-run --factory-name adf-retaillh-dev \
  --resource-group rg-retaillh-dev --name pl_ingest_customers
az datafactory pipeline create-run --factory-name adf-retaillh-dev \
  --resource-group rg-retaillh-dev --name pl_ingest_products
az datafactory pipeline create-run --factory-name adf-retaillh-dev \
  --resource-group rg-retaillh-dev --name pl_ingest_transactions
# All three → Succeeded (bronze/ container populated with Parquet files)
```

### Week 4 — Databricks + Lakeflow Pipeline
```bash
# Generate a PAT in Databricks UI → User Settings → Developer → Access Tokens
export DATABRICKS_TOKEN="dapi..."

# One-shot setup: Unity Catalog + storage credential + bundle deploy + pipeline start
bash infra/setup_databricks.sh
```
Or manually:
```bash
cd databricks
databricks bundle deploy --target dev \
  --var "storage_account=stretaillhdev" \
  --var "databricks_host=https://adb-7405615013053011.11.azuredatabricks.net"
databricks pipelines start --pipeline-id <id-from-bundle-output>
```

### Week 5 — Machine Learning
Once the Lakeflow pipeline completes (gold.customer_360 + gold.daily_kpis populated):
```bash
# Trigger the weekly ML retrain job
databricks jobs run-now --job-name retail-ml-retrain-dev
```
Or run the notebooks manually in the Databricks UI in order:
1. `src/ml/segmentation.py`
2. `src/ml/demand_forecast.py`
3. `src/ml/model_validation.py`

### Week 6 — CI/CD (GitHub Actions)
```bash
# Initialise repo, push code, set all GitHub Actions secrets
export DATABRICKS_TOKEN="dapi..."
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
bash infra/setup_github.sh <your-github-username> retail-lakehouse

# On every push to main:
#   terraform.yml       → terraform plan/apply on infra/ changes
#   databricks_deploy.yml → bundle validate → deploy → smoke test → promote
```

---

## Running Tests

```bash
pip install pytest pyspark delta-spark
pytest tests/ -v
```

---

## GitHub Actions Secrets Required

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | Service principal app ID (create with `az ad sp create-for-rbac`) |
| `AZURE_CLIENT_SECRET` | Service principal secret |
| `AZURE_SUBSCRIPTION_ID` | `25089613-0f49-4b36-aeff-c96d9aa648c4` |
| `AZURE_TENANT_ID` | From `az account show --query tenantId` |
| `DATABRICKS_HOST` | `https://adb-7405615013053011.11.azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Generate in Databricks UI → User Settings → Developer |
| `SQL_SERVER_PASSWORD` | `RetailLH@2026!` |
| `SQL_SERVER_HOST` | `20.62.125.63` |
| `STORAGE_ACCOUNT_NAME` | `stretaillhdev` |
| `CLUSTER_POLICY_ID` | `00070BB969B7B0BF` |

Run `bash infra/setup_github.sh <username>` to set all secrets automatically.

---

## Unity Catalog Access Control

| Principal | Permissions |
|---|---|
| `analysts` group | READ on `silver.*`, `gold.*` |
| `data_engineers` group | READ/WRITE on `bronze.*`, `silver.*`, `gold.*` |
| `ml_service_principal` | READ on `silver.*`, WRITE on `gold.demand_forecast`, `ml.*` |
| `adf_service_principal` | WRITE on `bronze.*` only |

---

## What This Project Demonstrates

- **SHIR setup** — bridges cloud ADF to local SQL Server through a firewall; appears in nearly every enterprise DE role
- **Watermark-based incremental loading** — not a bulk copy; real CDC-lite pattern for transactions
- **Lakeflow pipeline with quarantine tables** — not "dropped bad rows" but evidence of where they went and why
- **MLflow Model Registry with promotion gate** — model doesn't go to production unless MAPE < 15%
- **Unity Catalog column-level lineage** — free governance evidence; screenshot this for your README
- **Declarative Automation Bundles with dev/prod targets** — proves dev/prod separation and CI/CD thinking

---

## Dataset Attribution

UCI Online Retail II — Dua, D. and Graff, C. (2019). UCI Machine Learning Repository. Licensed under CC BY 4.0.
