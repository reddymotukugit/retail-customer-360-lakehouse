variable "project_name" {
  description = "Short project identifier — used as prefix for all resource names."
  type        = string
  default     = "retaillh"
}

variable "environment" {
  description = "Deployment environment (dev or prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'."
  }
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "australiaeast"
}

variable "sql_server_password" {
  description = "Password for the local SQL Server SA account. Stored in Key Vault."
  type        = string
  sensitive   = true
}

variable "sql_server_host" {
  description = "Local machine IP or hostname that SQL Server Express is running on."
  type        = string
}

variable "databricks_sku" {
  description = "Azure Databricks workspace SKU. Must be 'premium' — Standard tier is retired."
  type        = string
  default     = "premium"
}

variable "tags" {
  description = "Common tags applied to all resources."
  type        = map(string)
  default = {
    project     = "retail-customer-360"
    managed_by  = "terraform"
    owner       = "data-engineering"
  }
}
