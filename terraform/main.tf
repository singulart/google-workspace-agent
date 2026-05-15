data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default_per_az" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "agent_runtime" {
  name        = "${var.name_prefix}-agentcore-runtime"
  description = "Egress for Bedrock AgentCore runtime in VPC"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description      = "HTTPS (APIs, Bedrock, etc.)"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "${var.name_prefix}-agentcore-runtime"
  }
}

# --- Encrypted uploads bucket (SSE-S3; no extra KMS key monthly fee) ---

resource "aws_s3_bucket" "uploads" {
  bucket = var.s3_uploads_bucket
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Suspended"
  }
}

# --- Session-scoped reasoning (on-demand; AWS-owned encryption at rest) ---

resource "aws_dynamodb_table" "sessions" {
  name         = var.dynamodb_sessions_table
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "session_id"
  range_key = "reasoning_key"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "reasoning_key"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = false
  }

  tags = {
    Name = var.dynamodb_sessions_table
  }
}

# --- ECR (ARM64 image required before runtime can succeed) ---

resource "aws_ecr_repository" "agent" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# --- AgentCore Memory: minimum retention, no strategies (no extra model/strategy charges) ---

resource "aws_bedrockagentcore_memory" "main" {
  name                  = "${var.name_prefix}-memory"
  description           = "Short-term AgentCore memory; strategies disabled for minimal cost."
  event_expiry_duration = var.memory_event_retention_days
}

# --- Runtime IAM ---

data "aws_iam_policy_document" "agent_runtime_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agent_runtime" {
  name               = "${var.name_prefix}-agentcore-runtime"
  assume_role_policy = data.aws_iam_policy_document.agent_runtime_assume.json
}

data "aws_iam_policy_document" "agent_runtime_inline" {
  statement {
    sid    = "EcrAuth"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.agent.arn]
  }

  statement {
    sid    = "S3Uploads"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.uploads.arn]
  }

  statement {
    sid    = "S3Objects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }

  statement {
    sid    = "DynamoSessions"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:DescribeTable",
    ]
    resources = [aws_dynamodb_table.sessions.arn]
  }

  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "BedrockAgentCoreMemory"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:CreateEvent",
      "bedrock-agentcore:GetEvent",
      "bedrock-agentcore:ListEvents",
      "bedrock-agentcore:DeleteEvent",
      "bedrock-agentcore:BatchCreateMemoryRecords",
      "bedrock-agentcore:BatchUpdateMemoryRecords",
      "bedrock-agentcore:BatchDeleteMemoryRecords",
      "bedrock-agentcore:GetMemoryRecord",
      "bedrock-agentcore:DeleteMemoryRecord",
      "bedrock-agentcore:ListMemoryRecords",
      "bedrock-agentcore:RetrieveMemoryRecords",
    ]
    resources = [aws_bedrockagentcore_memory.main.arn]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/vendedlogs/bedrock-agentcore/*"]
  }
}

resource "aws_iam_role_policy" "agent_runtime" {
  name = "${var.name_prefix}-agentcore-runtime-inline"
  role = aws_iam_role.agent_runtime.id
  policy = data.aws_iam_policy_document.agent_runtime_inline.json

  depends_on = [aws_bedrockagentcore_memory.main]
}

# --- AgentCore runtime (container) + endpoint ---

resource "aws_bedrockagentcore_agent_runtime" "main" {
  agent_runtime_name = "${var.name_prefix}-runtime"
  description        = "Vincent agent (container) on default VPC public subnets"
  role_arn           = aws_iam_role.agent_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.container_image_tag}"
    }
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = data.aws_subnets.default_per_az.ids
      security_groups = [aws_security_group.agent_runtime.id]
    }
  }

  environment_variables = {
    UPLOADS_BUCKET_NAME = aws_s3_bucket.uploads.bucket
    SESSIONS_TABLE_NAME = aws_dynamodb_table.sessions.name
    MEMORY_ID           = aws_bedrockagentcore_memory.main.id
    AWS_REGION          = var.aws_region
  }

  depends_on = [aws_iam_role_policy.agent_runtime]
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "main" {
  name             = "${var.name_prefix}-endpoint"
  description      = "Invoke surface for ${var.name_prefix} runtime"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
}
