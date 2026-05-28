variable "container_image_tag" {
  type        = string
  description = "ECR tag for the Vincent agent"
  default     = "2026-05-27-008"
}

variable "gmail_mcp_container_image_tag" {
  type        = string
  description = "ECR tag for Gmail MCP"
  default     = "2026-05-27-002"
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  type        = string
  description = "App name"
  default     = "vincent"
}

variable "s3_uploads_bucket" {
  type        = string
  description = "Globally unique S3 bucket name for encrypted file uploads."
  default     = "vincent-bin"
}

variable "dynamodb_sessions_table" {
  type        = string
  description = "DynamoDB table name for session-scoped reasoning records."
  default     = "vincent-sessions"
}

variable "ecr_repository_name" {
  type        = string
  description = "ECR repository for the AgentCore ARM64 container image."
  default     = "vincent-agent"
}

variable "memory_event_retention_days" {
  type        = number
  description = "AgentCore Memory event expiry (7–365). Minimum (7) minimizes storage duration for cost."
  default     = 7

  validation {
    condition     = var.memory_event_retention_days >= 7 && var.memory_event_retention_days <= 365
    error_message = "memory_event_retention_days must be between 7 and 365."
  }
}

variable "lambda_artifacts_bucket" {
  type        = string
  description = "S3 bucket holding Lambda deployment.zip artifacts (see deploy_lambda.sh)."
  default     = "argorand-lambdas-repository"
}

variable "api_gateway_stage_name" {
  type        = string
  description = "API Gateway stage name (path is still /v1/vincent on the API)."
  default     = "prod"
}

variable "google_chat_auth_mode" {
  type        = string
  description = "Google Chat JWT mode: http_url (OIDC audience = API invoke URL; default) or project_number (audience = GCP project number)."
  default     = "http_url"

  validation {
    condition     = contains(["project_number", "http_url"], var.google_chat_auth_mode)
    error_message = "google_chat_auth_mode must be project_number or http_url."
  }
}

variable "google_chat_project_number" {
  type        = string
  description = "GCP project number for Chat app Authentication audience (project_number mode)."
  default     = "886715385828"
}

variable "google_chat_http_audience" {
  type        = string
  description = "Optional override for JWT audience (http_url). If empty, uses the same URL as google_chat_webhook_url (rest API invoke URL + /v1/vincent; verified against stage.invoke_url via check block)."
  default     = ""
}

