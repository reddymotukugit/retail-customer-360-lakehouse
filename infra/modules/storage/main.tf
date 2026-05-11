variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "project_name"        { type = string }
variable "environment"         { type = string }
variable "tags"                { type = map(string) }

# Storage account names must be globally unique, 3-24 chars, lowercase alphanumeric only
locals {
  # e.g. "stretaillhdev"
  storage_account_name = substr(
    lower(replace("st${var.project_name}${var.environment}", "-", "")),
    0, 24
  )
}

resource "azurerm_storage_account" "this" {
  name                     = local.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  # Enable hierarchical namespace = ADLS Gen2
  is_hns_enabled = true

  # Disable public blob access — data is accessed via service principals only
  allow_nested_items_to_be_public = false

  min_tls_version = "TLS1_2"

  tags = var.tags
}

# Bronze container — raw Parquet files from ADF. Append-only, never deleted.
resource "azurerm_storage_container" "bronze" {
  name                  = "bronze"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# Silver container — cleaned Delta tables (managed by Databricks)
resource "azurerm_storage_container" "silver" {
  name                  = "silver"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# Gold container — curated Delta tables (customer 360, KPIs, forecasts)
resource "azurerm_storage_container" "gold" {
  name                  = "gold"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

output "storage_account_name" {
  value = azurerm_storage_account.this.name
}
output "storage_account_id" {
  value = azurerm_storage_account.this.id
}
output "primary_access_key"   {
  value     = azurerm_storage_account.this.primary_access_key
  sensitive = true
}
output "dfs_endpoint" {
  value = "abfss://${azurerm_storage_account.this.name}.dfs.core.windows.net"
}
