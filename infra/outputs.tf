output "resource_group_name" {
  description = "Name of the Azure Resource Group."
  value       = azurerm_resource_group.this.name
}

output "storage_account_name" {
  description = "ADLS Gen2 Storage Account name."
  value       = module.storage.storage_account_name
}

output "storage_dfs_endpoint" {
  description = "ADLS Gen2 DFS endpoint (abfss:// primary endpoint)."
  value       = module.storage.dfs_endpoint
}

output "key_vault_name" {
  description = "Azure Key Vault name."
  value       = module.keyvault.key_vault_name
}

output "key_vault_uri" {
  description = "Azure Key Vault URI."
  value       = module.keyvault.key_vault_uri
}

output "adf_name" {
  description = "Azure Data Factory name."
  value       = module.adf.adf_name
}

output "adf_identity_principal_id" {
  description = "Managed Identity principal ID for ADF — used to assign RBAC roles."
  value       = module.adf.identity_principal_id
}

output "databricks_workspace_url" {
  description = "Databricks workspace URL."
  value       = azurerm_databricks_workspace.this.workspace_url
}

output "databricks_workspace_id" {
  description = "Databricks workspace resource ID."
  value       = azurerm_databricks_workspace.this.id
}

output "cluster_policy_id" {
  description = "ID of the Jobs Compute cluster policy."
  value       = databricks_cluster_policy.jobs_compute.id
}
