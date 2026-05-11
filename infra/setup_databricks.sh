#!/usr/bin/env bash
# =============================================================================
# setup_databricks.sh
# =============================================================================
# One-shot Databricks setup for the Retail Lakehouse project.
#
# What it does:
#   1. Configures the Databricks CLI using your PAT
#   2. Creates a Storage Credential + External Location (ADLS Gen2 access)
#   3. Creates Unity Catalog: retail_prod  (schemas: bronze, silver, gold, ml)
#   4. Deploys the Declarative Automation Bundle (Lakeflow + Jobs) to dev
#   5. Triggers the dev Lakeflow pipeline for a smoke test
#
# Prerequisites (run once on your Mac):
#   brew install databricks
#   az login
#
# Usage:
#   export DATABRICKS_TOKEN="dapiXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
#   bash infra/setup_databricks.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Hardcoded from Terraform state — update if you redeploy infra
# ---------------------------------------------------------------------------
WORKSPACE_URL="https://adb-7405615013053011.11.azuredatabricks.net"
STORAGE_ACCOUNT="stretaillhdev"
SUBSCRIPTION_ID="25089613-0f49-4b36-aeff-c96d9aa648c4"
RESOURCE_GROUP="rg-retaillh-dev"
CLUSTER_POLICY_ID="00070BB969B7B0BF"

# ---------------------------------------------------------------------------
# Validate token is set
# ---------------------------------------------------------------------------
if [[ -z "${DATABRICKS_TOKEN:-}" ]]; then
  echo "ERROR: DATABRICKS_TOKEN is not set."
  echo "Generate a Personal Access Token in Databricks:"
  echo "  ${WORKSPACE_URL}/#setting/account/token"
  echo ""
  echo "Then run: export DATABRICKS_TOKEN='dapi...'"
  exit 1
fi

export DATABRICKS_HOST="${WORKSPACE_URL}"

echo "=================================================="
echo " Retail Lakehouse — Databricks Setup"
echo "=================================================="
echo " Workspace: ${WORKSPACE_URL}"
echo " Storage:   ${STORAGE_ACCOUNT}"
echo ""

# ---------------------------------------------------------------------------
# Step 1 — Configure Databricks CLI
# ---------------------------------------------------------------------------
echo "[1/5] Configuring Databricks CLI..."
databricks configure --host "${WORKSPACE_URL}" --token "${DATABRICKS_TOKEN}" --profile DEFAULT
echo "  CLI configured."

# ---------------------------------------------------------------------------
# Step 2 — Storage Credential (Managed Identity)
# ---------------------------------------------------------------------------
echo "[2/5] Creating storage credential + external location..."

# Use the Azure Databricks Access Connector for Unity Catalog
# The connector's managed identity must have 'Storage Blob Data Contributor' on the ADLS account.
# We provision it from the workspace REST API.

CONNECTOR_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Databricks/accessConnectors/ac-retaillh-dev"

# Check if connector exists; if not, create it via az CLI
if az databricks access-connector show \
      --name "ac-retaillh-dev" \
      --resource-group "${RESOURCE_GROUP}" \
      --subscription "${SUBSCRIPTION_ID}" &>/dev/null; then
  echo "  Access connector already exists."
else
  echo "  Creating Azure Databricks Access Connector..."
  az databricks access-connector create \
    --name "ac-retaillh-dev" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "australiaeast" \
    --identity-type SystemAssigned
fi

# Get the Access Connector's managed identity principal ID
CONNECTOR_OID=$(az databricks access-connector show \
  --name "ac-retaillh-dev" \
  --resource-group "${RESOURCE_GROUP}" \
  --query "identity.principalId" -o tsv)
echo "  Access Connector OID: ${CONNECTOR_OID}"

# Grant Storage Blob Data Contributor on the ADLS account
STORAGE_ID=$(az storage account show \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query "id" -o tsv)

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee "${CONNECTOR_OID}" \
  --scope "${STORAGE_ID}" 2>/dev/null || echo "  Role assignment already exists."

echo "  Storage RBAC assigned."

# Create Unity Catalog storage credential via Databricks REST API
databricks storage-credentials create \
  --json "{
    \"name\": \"adls_retaillh_dev\",
    \"azure_managed_identity\": {
      \"access_connector_id\": \"${CONNECTOR_ID}\"
    },
    \"comment\": \"Managed identity for ADLS Gen2 access — retail lakehouse dev\"
  }" 2>/dev/null || echo "  Storage credential already exists."

# Create external location covering the entire storage account
databricks external-locations create \
  --json "{
    \"name\": \"bronze_retaillh_dev\",
    \"url\": \"abfss://bronze@${STORAGE_ACCOUNT}.dfs.core.windows.net\",
    \"credential_name\": \"adls_retaillh_dev\",
    \"comment\": \"Bronze container for retail lakehouse dev\"
  }" 2>/dev/null || echo "  External location already exists."

echo "  Storage credential + external location ready."

# ---------------------------------------------------------------------------
# Step 3 — Unity Catalog: retail_prod catalog + schemas
# ---------------------------------------------------------------------------
echo "[3/5] Setting up Unity Catalog (retail_prod)..."

python3 - <<'PYEOF'
import requests, os, json

host  = os.environ["DATABRICKS_HOST"]
token = os.environ["DATABRICKS_TOKEN"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
base = f"{host}/api/2.1/unity-catalog"

def uc_post(path, body, ok_on_conflict=True):
    r = requests.post(f"{base}/{path}", headers=headers, json=body)
    if r.status_code == 409 and ok_on_conflict:
        print(f"    Already exists: {body.get('name', path)}")
        return
    r.raise_for_status()
    print(f"    Created: {body.get('name', path)}")

# Catalog
uc_post("catalogs", {"name": "retail_prod", "comment": "Retail Customer 360 & Demand Forecasting Lakehouse"})

# Schemas
for schema in ["bronze", "silver", "gold", "ml"]:
    uc_post("schemas", {
        "catalog_name": "retail_prod",
        "name": schema,
        "comment": f"Retail lakehouse {schema} layer"
    })

print("  Unity Catalog retail_prod with all schemas is ready.")
PYEOF

echo "  Unity Catalog setup complete."

# ---------------------------------------------------------------------------
# Step 4 — Deploy Declarative Automation Bundle
# ---------------------------------------------------------------------------
echo "[4/5] Deploying Databricks bundle (dev target)..."

cd "$(dirname "$0")/../databricks"

databricks bundle deploy \
  --target dev \
  --var "storage_account=${STORAGE_ACCOUNT}" \
  --var "databricks_host=${WORKSPACE_URL}" \
  --force-lock

echo "  Bundle deployed to dev."

# ---------------------------------------------------------------------------
# Step 5 — Smoke test: trigger Lakeflow pipeline
# ---------------------------------------------------------------------------
echo "[5/5] Triggering Lakeflow pipeline smoke test..."

PIPELINE_ID=$(databricks pipelines list \
  --output json 2>/dev/null \
  | python3 -c "
import sys,json
pls=json.load(sys.stdin)
for p in pls.get('statuses',[]):
    if 'retail-lakehouse-pipeline-dev' in p.get('name',''):
        print(p['pipeline_id'])
        break
")

if [[ -z "$PIPELINE_ID" ]]; then
  echo "  WARN: Could not find Lakeflow pipeline. Run manually:"
  echo "    databricks pipelines start --pipeline-id <id>"
else
  echo "  Pipeline ID: ${PIPELINE_ID}"
  databricks pipelines start --pipeline-id "${PIPELINE_ID}"
  echo "  Lakeflow pipeline started. Monitor at:"
  echo "    ${WORKSPACE_URL}/#joblist/pipelines/${PIPELINE_ID}"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=================================================="
echo " Setup complete!"
echo "=================================================="
echo ""
echo " Databricks workspace:"
echo "   ${WORKSPACE_URL}"
echo ""
echo " Unity Catalog:"
echo "   Catalog: retail_prod"
echo "   Schemas: bronze | silver | gold | ml"
echo ""
echo " Next steps:"
echo "   1. Monitor Lakeflow pipeline in Databricks UI"
echo "   2. Run ML retrain job once pipeline completes:"
echo "        databricks jobs run-now --job-name retail-ml-retrain-dev"
echo "   3. Connect Power BI to:"
echo "        Server: ${WORKSPACE_URL}"
echo "        Catalog: retail_prod  Schema: gold"
echo ""
echo " GitHub Actions secrets needed:"
echo "   DATABRICKS_HOST        = ${WORKSPACE_URL}"
echo "   DATABRICKS_TOKEN       = \$DATABRICKS_TOKEN"
echo "   STORAGE_ACCOUNT_NAME   = ${STORAGE_ACCOUNT}"
echo "   CLUSTER_POLICY_ID      = ${CLUSTER_POLICY_ID}"
echo "   AZURE_CLIENT_ID        = (from: az ad sp show --id ...)"
echo "   AZURE_CLIENT_SECRET    = (from: keyvault or your SP secret)"
echo "   AZURE_SUBSCRIPTION_ID  = ${SUBSCRIPTION_ID}"
echo "   AZURE_TENANT_ID        = (from: az account show)"
echo "   SQL_SERVER_PASSWORD    = RetailLH@2026!"
echo "   SQL_SERVER_HOST        = 20.62.125.63"
