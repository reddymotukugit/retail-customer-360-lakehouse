#!/usr/bin/env bash
# =============================================================================
# deploy_adf.sh
# Deploys all ADF linked services, datasets, and pipelines to Azure.
#
# Prerequisites:
#   - az CLI logged in to Pay-As-You-Go subscription
#   - terraform applied in infra/ (outputs available)
#   - run from project root: bash adf/deploy_adf.sh
# =============================================================================

set -euo pipefail

ADF_NAME="adf-retaillh-dev"
RG="rg-retaillh-dev"

echo "=== Retail Lakehouse — ADF Deployment ==="
echo "Factory : $ADF_NAME"
echo "RG      : $RG"
echo ""

# ---------------------------------------------------------------------------
# Confirm we're on the right subscription
# ---------------------------------------------------------------------------
CURRENT_SUB=$(az account show --query name -o tsv)
echo "Active subscription: $CURRENT_SUB"

# If on the free trial sub, switch
az account set --subscription "$(az account list --query "[?contains(name,'Pay')].id" -o tsv | head -1)" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Get the actual Key Vault URI and storage DFS endpoint from Terraform outputs
# ---------------------------------------------------------------------------
echo ""
echo "Reading Terraform outputs..."
cd infra

KV_URI=$(terraform output -raw key_vault_uri 2>/dev/null || echo "https://kv-retaillh-dev.vault.azure.net/")
STORAGE_DFS=$(terraform output -raw storage_dfs_endpoint 2>/dev/null \
  | sed 's|abfss://||' \
  | sed 's|\.dfs\.core\.windows\.net.*|.dfs.core.windows.net|' \
  || echo "https://stretaillhdev.dfs.core.windows.net")

# storage_dfs_endpoint from TF is "abfss://stretaillhdev.dfs.core.windows.net"
# we need the https:// form for ADF dataset URL
STORAGE_URL=$(terraform output -raw storage_dfs_endpoint 2>/dev/null \
  | sed 's|abfss://|https://|' \
  | sed 's|\.dfs\.core\.windows\.net.*|.dfs.core.windows.net|' \
  || echo "https://stretaillhdev.dfs.core.windows.net")

cd ..

echo "Key Vault URI   : $KV_URI"
echo "Storage URL     : $STORAGE_URL"
echo ""

# ---------------------------------------------------------------------------
# Update ls_keyvault.json with the actual KV URI (in case it differs)
# ---------------------------------------------------------------------------
python3 -c "
import json, sys
with open('adf/linked_services/ls_keyvault.json') as f:
    obj = json.load(f)
obj['properties']['typeProperties']['baseUrl'] = '${KV_URI}'
with open('adf/linked_services/ls_keyvault.json', 'w') as f:
    json.dump(obj, f, indent=2)
print('  Updated ls_keyvault.json with KV URI')
"

# Also patch storage datasets with correct storage URL
for ds in adf/datasets/ds_adls_transactions_parquet.json \
          adf/datasets/ds_adls_customers_parquet.json \
          adf/datasets/ds_adls_products_parquet.json; do
  python3 -c "
import json
with open('${ds}') as f:
    obj = json.load(f)
obj['properties']['parameters']['storage_account_url']['defaultValue'] = '${STORAGE_URL}'
with open('${ds}', 'w') as f:
    json.dump(obj, f, indent=2)
print('  Updated ${ds} with storage URL')
"
done

echo ""
echo "--- Step 1: Linked Services (order matters: KV first) ---"

deploy_ls() {
  local name="$1"
  local file="$2"
  echo -n "  Deploying linked service '$name'... "
  # CLI --properties expects only the inner 'properties' object, not the full ARM wrapper
  local props
  props=$(python3 -c "import json,sys; d=json.load(open('$file')); print(json.dumps(d.get('properties',d)))")
  az datafactory linked-service create \
    --factory-name "$ADF_NAME" \
    --resource-group "$RG" \
    --name "$name" \
    --properties "$props" \
    --output none
  echo "done."
}

deploy_ls "ls_keyvault"        "adf/linked_services/ls_keyvault.json"
deploy_ls "ls_sqlserver_onprem" "adf/linked_services/ls_sqlserver_onprem.json"
deploy_ls "ls_adls_gen2"       "adf/linked_services/ls_adls_gen2.json"

echo ""
echo "--- Step 2: Datasets (SQL Server) ---"

deploy_ds() {
  local name="$1"
  local file="$2"
  echo -n "  Deploying dataset '$name'... "
  local props
  props=$(python3 -c "import json,sys; d=json.load(open('$file')); print(json.dumps(d.get('properties',d)))")
  az datafactory dataset create \
    --factory-name "$ADF_NAME" \
    --resource-group "$RG" \
    --name "$name" \
    --properties "$props" \
    --output none
  echo "done."
}

deploy_ds "ds_sqlserver_transactions" "adf/datasets/ds_sqlserver_transactions.json"
deploy_ds "ds_sqlserver_customers"    "adf/datasets/ds_sqlserver_customers.json"
deploy_ds "ds_sqlserver_products"     "adf/datasets/ds_sqlserver_products.json"
deploy_ds "ds_sqlserver_watermarks"   "adf/datasets/ds_sqlserver_watermarks.json"

echo ""
echo "--- Step 3: Datasets (ADLS Gen2 Parquet) ---"

deploy_ds "ds_adls_transactions_parquet" "adf/datasets/ds_adls_transactions_parquet.json"
deploy_ds "ds_adls_customers_parquet"    "adf/datasets/ds_adls_customers_parquet.json"
deploy_ds "ds_adls_products_parquet"     "adf/datasets/ds_adls_products_parquet.json"

echo ""
echo "--- Step 4: Pipelines ---"

deploy_pl() {
  local name="$1"
  local file="$2"
  echo -n "  Deploying pipeline '$name'... "
  local props
  props=$(python3 -c "import json,sys; d=json.load(open('$file')); print(json.dumps(d.get('properties',d)))")
  az datafactory pipeline create \
    --factory-name "$ADF_NAME" \
    --resource-group "$RG" \
    --name "$name" \
    --pipeline "$props" \
    --output none
  echo "done."
}

deploy_pl "pl_ingest_transactions" "adf/pl_ingest_transactions.json"
deploy_pl "pl_ingest_customers"    "adf/pl_ingest_customers.json"
deploy_pl "pl_ingest_products"     "adf/pl_ingest_products.json"

echo ""
echo "=== ADF deployment complete! ==="
echo ""
echo "Next steps:"
echo "  1. Open ADF Studio → Monitor → check SHIR shows 'Running'"
echo "  2. Test connection on ls_sqlserver_onprem (pass sql_server_host=20.62.125.63)"
echo "  3. Trigger pl_ingest_transactions, pl_ingest_customers, pl_ingest_products"
echo "  4. Check bronze container in ADLS Gen2 for Parquet files"
