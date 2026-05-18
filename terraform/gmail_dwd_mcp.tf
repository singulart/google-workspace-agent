# FastMCP Gmail DWD server (artifact: s3://<bucket>/gmail-dwd-mcp/deployment.zip).
# Exposed only via Function URL with AWS_IAM; invoke is limited to the AgentCore Gateway role.

data "aws_s3_object" "gmail_dwd_mcp_zip" {
  bucket = var.lambda_artifacts_bucket
  key    = "gmail-dwd-mcp/deployment.zip"
}


locals {
  gmail_dwd_mcp_source_hash = coalesce(
    trimspace(replace(data.aws_s3_object.gmail_dwd_mcp_zip.checksum_sha256, "\"", "")),
    trimspace(replace(data.aws_s3_object.gmail_dwd_mcp_zip.etag, "\"", "")),
  )
}

resource "aws_ssm_parameter" "gmail_dwd_wif" {
  name        = "/${var.name_prefix}/gmail-wif-config"
  description = "Settings for user impersonation."
  type        = "SecureString"
  value       = "dummy"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.name_prefix}-gmail-wif-config"
  }
}

resource "aws_iam_role" "gmail_dwd_mcp" {
  name = "${var.name_prefix}-gmail-dwd-mcp"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "gmail_dwd_mcp_basic" {
  role       = aws_iam_role.gmail_dwd_mcp.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "gmail_dwd_mcp_inline" {
  statement {
    sid    = "ReadWifConfigFromSsm"
    effect = "Allow"
    actions = [
      "ssm:GetParameter*"
    ]
    resources = [aws_ssm_parameter.gmail_dwd_wif.arn]
  }

}

resource "aws_iam_role_policy" "gmail_dwd_mcp" {
  name   = "${var.name_prefix}-gmail-dwd-mcp"
  role   = aws_iam_role.gmail_dwd_mcp.id
  policy = data.aws_iam_policy_document.gmail_dwd_mcp_inline.json
}

resource "aws_cloudwatch_log_group" "gmail_dwd_mcp" {
  name              = "/aws/lambda/${var.name_prefix}-gmail-dwd-mcp"
  retention_in_days = 14
}

resource "aws_lambda_function" "gmail_dwd_mcp" {
  function_name = "${var.name_prefix}-gmail-dwd-mcp"
  role          = aws_iam_role.gmail_dwd_mcp.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.14"
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 512

  s3_bucket         = var.lambda_artifacts_bucket
  s3_key            = data.aws_s3_object.gmail_dwd_mcp_zip.key
  source_code_hash  = local.gmail_dwd_mcp_source_hash
  s3_object_version = data.aws_s3_object.gmail_dwd_mcp_zip.version_id != null && data.aws_s3_object.gmail_dwd_mcp_zip.version_id != "" ? data.aws_s3_object.gmail_dwd_mcp_zip.version_id : null

  environment {
    variables = merge(
      {
        GMAIL_WIF_SSM_PARAMETER = aws_ssm_parameter.gmail_dwd_wif.name
      },
    )
  }

  depends_on = [
    aws_cloudwatch_log_group.gmail_dwd_mcp,
    aws_iam_role_policy.gmail_dwd_mcp,
  ]
}

# AWS_IAM: anonymous callers cannot invoke even if they know the URL.
resource "aws_lambda_function_url" "gmail_dwd_mcp" {
  function_name      = aws_lambda_function.gmail_dwd_mcp.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"
}

# Resource-based policy: only the AgentCore Gateway execution role may invoke the URL.
resource "aws_lambda_permission" "gmail_dwd_mcp_gateway_function_url" {
  statement_id           = "AllowAgentCoreGatewayInvokeFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.gmail_dwd_mcp.function_name
  principal              = aws_iam_role.agentcore_gateway.arn
  function_url_auth_type = "AWS_IAM"
}
