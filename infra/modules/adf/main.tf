variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "project_name"        { type = string }
variable "environment"         { type = string }
variable "key_vault_id"        { type = string }
variable "storage_account_id"  { type = string }
variable "tags"                { type = map(string) }

resource "azurerm_data_factory" "this" {
  name                = "adf-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location

  # System-assigned managed identity — used for Key Vault access and ADLS Gen2 access
  identity {
    type = "SystemAssigned"
  }

  # Public network access enabled — required for SHIR to register from outside VNet
  public_network_enabled = true

  tags = var.tags
}

# Grant ADF's managed identity access to Key Vault secrets
resource "azurerm_key_vault_access_policy" "adf" {
  key_vault_id = var.key_vault_id
  tenant_id    = azurerm_data_factory.this.identity[0].tenant_id
  object_id    = azurerm_data_factory.this.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}

# Grant ADF's managed identity Storage Blob Data Contributor on ADLS Gen2
resource "azurerm_role_assignment" "adf_storage" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.this.identity[0].principal_id
}

# Self-Hosted Integration Runtime definition
# After applying, download the registration key from the ADF Studio and install
# the SHIR software on your local machine using that key.
resource "azurerm_data_factory_integration_runtime_self_hosted" "shir" {
  name            = "shir-onprem-sqlserver"
  data_factory_id = azurerm_data_factory.this.id

  description = "Self-Hosted IR bridging ADF to local SQL Server 2022 Express"
}

output "adf_name" {
  value = azurerm_data_factory.this.name
}
output "adf_id" {
  value = azurerm_data_factory.this.id
}
output "identity_principal_id" {
  value = azurerm_data_factory.this.identity[0].principal_id
}
output "shir_name" {
  value = azurerm_data_factory_integration_runtime_self_hosted.shir.name
}
