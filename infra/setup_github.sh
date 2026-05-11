#!/usr/bin/env bash
# =============================================================================
# setup_github.sh
# =============================================================================
# Initialises the GitHub repo and sets all Actions secrets.
#
# Prerequisites:
#   brew install gh
#   gh auth login
#   export DATABRICKS_TOKEN="dapi..."
#   export AZURE_CLIENT_SECRET="..."
#
# Usage:
#   bash infra/setup_github.sh <github-username> <repo-name>
#   e.g.: bash infra/setup_github.sh reddymotuku retail-lakehouse
# =============================================================================

set -euo pipefail

GITHUB_USER="${1:-}"
REPO_NAME="${2:-retail-lakehouse}"

if [[ -z "$GITHUB_USER" ]]; then
  echo "Usage: bash infra/setup_github.sh <github-username> [repo-name]"
  exit 1
fi

FULL_REPO="${GITHUB_USER}/${REPO_NAME}"

# ---------------------------------------------------------------------------
# Hardcoded from Terraform state
# ---------------------------------------------------------------------------
WORKSPACE_URL="https://adb-7405615013053011.11.azuredatabricks.net"
STORAGE_ACCOUNT="stretaillhdev"
SUBSCRIPTION_ID="25089613-0f49-4b36-aeff-c96d9aa648c4"
CLUSTER_POLICY_ID="00070BB969B7B0BF"
SQL_SERVER_HOST="20.62.125.63"
SQL_SERVER_PASSWORD="RetailLH@2026!"

AZURE_TENANT_ID=$(az account show --query "tenantId" -o tsv)

echo "=================================================="
echo " Retail Lakehouse — GitHub Setup"
echo " Repo: ${FULL_REPO}"
echo "=================================================="

# ---------------------------------------------------------------------------
# Step 1: Initialise git and create repo
# ---------------------------------------------------------------------------
cd "$(dirname "$0")/.."

echo "[1/4] Initialising git repository..."
if [[ ! -d .git ]]; then
  git init
  git branch -M main
fi

# Create .gitignore if missing
if [[ ! -f .gitignore ]]; then
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
*.egg

# Terraform
**/.terraform/
*.tfplan
*.tfstate
*.tfstate.*
.terraform.lock.hcl
terraform.tfvars

# macOS
.DS_Store

# IDE
.idea/
.vscode/

# Databricks
.databricks/
bundle.lock

# Sensitive
*.pem
*.key
*.env
.env*
EOF
fi

echo "[2/4] Creating GitHub repository: ${FULL_REPO}..."
gh repo create "${FULL_REPO}" \
  --public \
  --description "Production-grade Retail Customer 360 & Demand Forecasting Lakehouse on Azure" \
  --push \
  --source . 2>/dev/null || echo "  Repo may already exist; pushing to existing..."

# Add remote and push if repo already existed
git remote add origin "https://github.com/${FULL_REPO}.git" 2>/dev/null || \
  git remote set-url origin "https://github.com/${FULL_REPO}.git"

git add -A
git commit -m "Initial commit: retail lakehouse — ADF + Databricks + Lakeflow" \
  --allow-empty 2>/dev/null || true

git push -u origin main --force

echo "  Code pushed to https://github.com/${FULL_REPO}"

# ---------------------------------------------------------------------------
# Step 3: Set GitHub Actions secrets
# ---------------------------------------------------------------------------
echo "[3/4] Setting GitHub Actions secrets..."

check_env() {
  local var="$1"
  if [[ -z "${!var:-}" ]]; then
    echo "  WARN: ${var} is not set. Set it before running: export ${var}=..."
    return 1
  fi
  return 0
}

set_secret() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    echo "$value" | gh secret set "$name" --repo "${FULL_REPO}" --body -
    echo "  Set: $name"
  else
    echo "  SKIP (empty): $name"
  fi
}

# Databricks
set_secret "DATABRICKS_HOST"       "${WORKSPACE_URL}"
set_secret "DATABRICKS_TOKEN"      "${DATABRICKS_TOKEN:-}"
set_secret "STORAGE_ACCOUNT_NAME"  "${STORAGE_ACCOUNT}"
set_secret "CLUSTER_POLICY_ID"     "${CLUSTER_POLICY_ID}"

# Azure SP (Terraform)
set_secret "AZURE_SUBSCRIPTION_ID" "${SUBSCRIPTION_ID}"
set_secret "AZURE_TENANT_ID"       "${AZURE_TENANT_ID}"
set_secret "AZURE_CLIENT_ID"       "${AZURE_CLIENT_ID:-}"
set_secret "AZURE_CLIENT_SECRET"   "${AZURE_CLIENT_SECRET:-}"

# SQL Server
set_secret "SQL_SERVER_HOST"       "${SQL_SERVER_HOST}"
set_secret "SQL_SERVER_PASSWORD"   "${SQL_SERVER_PASSWORD}"

echo ""
echo "  Secrets set. Verify at:"
echo "  https://github.com/${FULL_REPO}/settings/secrets/actions"

# ---------------------------------------------------------------------------
# Step 4: Display remaining manual steps
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Manual steps remaining:"
echo ""
echo "  If AZURE_CLIENT_ID or AZURE_CLIENT_SECRET were skipped:"
echo "    1. Create a Service Principal:"
echo "         az ad sp create-for-rbac --name sp-retaillh-dev --role Contributor \\"
echo "           --scopes /subscriptions/${SUBSCRIPTION_ID}"
echo "    2. Copy the appId → AZURE_CLIENT_ID"
echo "         gh secret set AZURE_CLIENT_ID --repo ${FULL_REPO}"
echo "    3. Copy the password → AZURE_CLIENT_SECRET"
echo "         gh secret set AZURE_CLIENT_SECRET --repo ${FULL_REPO}"
echo ""
echo "=================================================="
echo " GitHub Setup Complete!"
echo " Repository: https://github.com/${FULL_REPO}"
echo "=================================================="
