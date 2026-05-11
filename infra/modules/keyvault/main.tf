variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "project_name"        { type = string }
variable "environment"         { type = string }
variable "tenant_id"           { type = string }
variable "object_id"           { type = string }
variable "sql_server_password" {
  type      = string
  sensitive = true
}
variable "storage_account_key" {
  type      = string
  sensitive = true
}
variable "tags" { type = map(string) }

locals {
  kv_name = "kv-${var.project_name}-${var.environment}"
}

resource "azurerm_key_vault" "this" {
  name                       = local.kv_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false  # set to true for production

  # Grant the deploying identity (you) full access
  access_policy {
    tenant_id = var.tenant_id
    object_id = var.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Recover", "Backup", "Restore", "Purge"
    ]
  }

  tags = var.tags
}

# SQL Server SA password — referenced by ADF linked service
resource "azurerm_key_vault_secret" "sql_password" {
  name         = "sql-server-password"
  value        = var.sql_server_password
  key_vault_id = azurerm_key_vault.this.id
}

# Storage account key — referenced by ADF linked service for ADLS Gen2
resource "azurerm_key_vault_secret" "storage_key" {
  name         = "adls-storage-account-key"
  value        = var.storage_account_key
  key_vault_id = azurerm_key_vault.this.id
}

output "key_vault_id" {
  value = azurerm_key_vault.this.id
}
output "key_vault_name" {
  value = azurerm_key_vault.this.name
}
output "key_vault_uri" {
  value = azurerm_key_vault.this.vault_uri
}
