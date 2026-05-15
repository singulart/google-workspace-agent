variable "aws_region" {
  type        = string
  description = "AWS region for all resources."
  default     = "us-east-1"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names (IAM, ECR, AgentCore, etc.)."
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

variable "container_image_tag" {
  type        = string
  description = "Image tag in ECR referenced by the AgentCore runtime (push this image before apply if the runtime is new)."
  default     = "latest"
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

variable "agentcore_subnet_availability_zone_ids" {
  type        = list(string)
  description = <<-EOT
    Subnet availability zone IDs where Bedrock Agent Core can place ENIs. In us-east-1 the
    service currently allows use1-az1, use1-az2, and use1-az4 only (AZ names like us-east-1a
    differ per account; use zone IDs from EC2 → Subnets or `aws ec2 describe-availability-zones`).
    Default subnets in other zone IDs must be excluded. Override when using another region.
  EOT
  default     = ["use1-az1", "use1-az2", "use1-az4"]
}
