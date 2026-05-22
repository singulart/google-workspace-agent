data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_partition" "current" {}

# Required before: aws xray update-trace-segment-destination --destination CloudWatchLogs
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html#observability-configure-builtin-cw
resource "aws_cloudwatch_log_resource_policy" "xray_transaction_search" {
  policy_name = "${var.name_prefix}-xray-transaction-search-spans"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TransactionSearchXRayAccess"
        Effect = "Allow"
        Principal = {
          Service = "xray.amazonaws.com"
        }
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans:*",
          "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/application-signals/data:*",
        ]
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:xray:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:*"
          }
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
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

# --- ECR ---

resource "aws_ecr_repository" "agent" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "mcp_gmail" {
  name                 = "${var.ecr_repository_name}-mcp-gmail"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# --- AgentCore Memory: minimum retention, no strategies (no extra model/strategy charges) ---

resource "aws_bedrockagentcore_memory" "main" {
  name                  = "${var.name_prefix}_memory"
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
    resources = [
      aws_ecr_repository.agent.arn,
      aws_ecr_repository.mcp_gmail.arn,
    ]
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
    sid    = "CloudWatchLogsVended"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/vendedlogs/bedrock-agentcore/*"]
  }

  # AgentCore execution role: runtime app + OTEL logs (see runtime-permissions.html)
  statement {
    sid    = "CloudWatchLogsRuntime"
    effect = "Allow"
    actions = [
      "logs:DescribeLogStreams",
      "logs:CreateLogGroup",
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
    ]
  }

  statement {
    sid    = "CloudWatchLogsDescribeGroups"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:*",
    ]
  }

  statement {
    sid    = "CloudWatchLogsRuntimeStreams"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
    ]
  }

  statement {
    sid    = "XRayTelemetry"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CloudWatchAgentCoreMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  statement {
    sid    = "ReadGcpWifCredentialConfigFromSsm"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [aws_ssm_parameter.gcp_wif.arn]
  }
}

resource "aws_iam_role_policy" "agent_runtime" {
  name   = "${var.name_prefix}-agentcore-runtime-inline"
  role   = aws_iam_role.agent_runtime.id
  policy = data.aws_iam_policy_document.agent_runtime_inline.json

  depends_on = [aws_bedrockagentcore_memory.main]
}

# --- AgentCore runtime (container) + endpoint ---

resource "aws_bedrockagentcore_agent_runtime" "main" {
  agent_runtime_name = "${var.name_prefix}_runtime"
  description        = "Vincent, a Google Workspace agent"
  role_arn           = aws_iam_role.agent_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.container_image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  environment_variables = {
    UPLOADS_BUCKET_NAME         = aws_s3_bucket.uploads.bucket
    SESSIONS_TABLE_NAME         = aws_dynamodb_table.sessions.name
    MEMORY_ID                   = aws_bedrockagentcore_memory.main.id
    GMAIL_MCP_GATEWAY_ARN       = aws_bedrockagentcore_gateway.gmail_mcp.gateway_arn
    GMAIL_MCP_GATEWAY_URL       = aws_bedrockagentcore_gateway.gmail_mcp.gateway_url
    GCP_WIF_CREDENTIAL_CONFIG_SSM_PARAMETER = aws_ssm_parameter.gcp_wif.name
    DEFAULT_TIMEZONE            = local.default_timezone
  }

  depends_on = [aws_iam_role_policy.agent_runtime]
}

# AgentCore console "Log deliveries and tracing" is driven by CloudWatch Logs V2
# deliveries (not the runtime IAM OTEL env alone). See:
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html

resource "aws_cloudwatch_log_group" "runtime_application_logs" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/APPLICATION_LOGS/${aws_bedrockagentcore_agent_runtime.main.agent_runtime_id}"
  retention_in_days = 30
  tags = {
    Name = "${var.name_prefix}-agentcore-application-logs"
  }
}

resource "aws_cloudwatch_log_delivery_source" "runtime_application_logs" {
  name         = "${var.name_prefix}-ac-runtime-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "runtime_application_logs" {
  name = "${var.name_prefix}-ac-runtime-app-logs-dest"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.runtime_application_logs.arn
  }
}

resource "aws_cloudwatch_log_delivery" "runtime_application_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_application_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_application_logs.arn

  depends_on = [
    aws_cloudwatch_log_delivery_source.runtime_application_logs,
    aws_cloudwatch_log_delivery_destination.runtime_application_logs,
  ]
}

resource "aws_cloudwatch_log_delivery_source" "runtime_traces" {
  name         = "${var.name_prefix}-ac-runtime-traces"
  log_type     = "TRACES"
  resource_arn = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "runtime_traces_xray" {
  name                      = "${var.name_prefix}-ac-runtime-traces-dest"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "runtime_traces" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_traces_xray.arn

  depends_on = [
    aws_cloudwatch_log_delivery_source.runtime_traces,
    aws_cloudwatch_log_delivery_destination.runtime_traces_xray,
  ]
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "main" {
  name             = "${var.name_prefix}_endpoint"
  description      = "Invoke surface for ${var.name_prefix} runtime"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
  # Named endpoints do not auto-track latest (unlike DEFAULT). Pin to the runtime
  # version Terraform just applied so image/tag updates reach production invokes.
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.main.agent_runtime_version
}

# --- Gmail MCP runtime (container) + endpoint ---

resource "aws_bedrockagentcore_agent_runtime" "gmail_mcp" {
  agent_runtime_name = "${var.name_prefix}_gmail_mcp"
  description        = "MCP server for agentic Gmail tasks"
  role_arn           = aws_iam_role.agent_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.mcp_gmail.repository_url}:${var.gmail_mcp_container_image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "MCP"
  }

  environment_variables = {
    GCP_WIF_CREDENTIAL_CONFIG_SSM_PARAMETER = aws_ssm_parameter.gcp_wif.name
  }

  depends_on = [aws_iam_role_policy.agent_runtime]
}

resource "aws_cloudwatch_log_group" "gmail_mcp_runtime_application_logs" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/APPLICATION_LOGS/${aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_id}"
  retention_in_days = 30

  tags = {
    Name = "${var.name_prefix}-gmail-mcp-application-logs"
  }
}

resource "aws_cloudwatch_log_delivery_source" "gmail_mcp_runtime_application_logs" {
  name         = "${var.name_prefix}-ac-gmail-mcp-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "gmail_mcp_runtime_application_logs" {
  name = "${var.name_prefix}-ac-gmail-mcp-app-logs-dest"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.gmail_mcp_runtime_application_logs.arn
  }
}

resource "aws_cloudwatch_log_delivery" "gmail_mcp_runtime_application_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gmail_mcp_runtime_application_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gmail_mcp_runtime_application_logs.arn

  depends_on = [
    aws_cloudwatch_log_delivery_source.gmail_mcp_runtime_application_logs,
    aws_cloudwatch_log_delivery_destination.gmail_mcp_runtime_application_logs,
  ]
}

resource "aws_cloudwatch_log_delivery_source" "gmail_mcp_runtime_traces" {
  name         = "${var.name_prefix}-ac-gmail-mcp-traces"
  log_type     = "TRACES"
  resource_arn = aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "gmail_mcp_runtime_traces_xray" {
  name                      = "${var.name_prefix}-ac-gmail-mcp-traces-dest"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "gmail_mcp_runtime_traces" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gmail_mcp_runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gmail_mcp_runtime_traces_xray.arn

  depends_on = [
    aws_cloudwatch_log_delivery_source.gmail_mcp_runtime_traces,
    aws_cloudwatch_log_delivery_destination.gmail_mcp_runtime_traces_xray,
  ]
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "gmail_mcp" {
  name                  = "gmail_mcp_endpoint"
  description           = "Invoke surface for gmail_mcp runtime"
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_id
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_version
}
