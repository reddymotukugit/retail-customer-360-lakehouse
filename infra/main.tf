terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }

  # Uncomment and configure after creating the storage account manually for remote state.
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "sttfstateretail"
  #   container_name       = "tfstate"
  #   key                  = "retail-lakehouse.tfstate"
  # }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

# Databricks provider — configured after workspace is created
provider "databricks" {
  host = azurerm_databricks_workspace.this.workspace_url
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
data "azurerm_client_config" "current" {}

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "this" {
  name     = "rg-${var.project_name}-${var.environment}"
  location = var.location
  tags     = var.tags
}

# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
module "storage" {
  source = "./modules/storage"

  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  project_name        = var.project_name
  environment         = var.environment
  tags                = var.tags
}

module "keyvault" {
  source = "./modules/keyvault"

  resource_group_name  = azurerm_resource_group.this.name
  location             = var.location
  project_name         = var.project_name
  environment          = var.environment
  tenant_id            = data.azurerm_client_config.current.tenant_id
  object_id            = data.azurerm_client_config.current.object_id
  sql_server_password  = var.sql_server_password
  storage_account_key  = module.storage.primary_access_key
  tags                 = var.tags
}

module "adf" {
  source = "./modules/adf"

  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  project_name        = var.project_name
  environment         = var.environment
  key_vault_id        = module.keyvault.key_vault_id
  storage_account_id  = module.storage.storage_account_id
  tags                = var.tags
}

# ---------------------------------------------------------------------------
# Azure Databricks Workspace  (Premium tier only — Standard is retired)
# ---------------------------------------------------------------------------
resource "azurerm_databricks_workspace" "this" {
  name                = "dbw-${var.project_name}-${var.environment}"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  sku                 = var.databricks_sku  # must be "premium"
  tags                = var.tags
}

# ---------------------------------------------------------------------------
# Databricks Cluster Policy — Jobs Compute
# $0.15/DBU vs $0.55/DBU for All-Purpose.  All pipelines use this.
# ---------------------------------------------------------------------------
resource "databricks_cluster_policy" "jobs_compute" {
  name = "jobs-compute-policy-${var.environment}"

  definition = jsonencode({
    "spark_version" = {
      type  = "allowlist"
      values = ["13.3.x-scala2.12", "14.3.x-scala2.12", "15.4.x-scala2.12"]
    }
    "node_type_id" = {
      type  = "allowlist"
      values = ["Standard_DS3_v2", "Standard_DS4_v2"]
    }
    "autotermination_minutes" = {
      type             = "fixed"
      value            = 20
      hidden           = false
    }
    "num_workers" = {
      type       = "range"
      minValue   = 0
      maxValue   = 2
    }
    "data_security_mode" = {
      type  = "fixed"
      value = "SINGLE_USER"
    }
  })
}
