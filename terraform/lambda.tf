# Vincent Chat bridge Lambdas (artifacts uploaded via ../deploy_lambda.sh)

data "aws_s3_object" "vincent_authorizer_zip" {
  bucket = var.lambda_artifacts_bucket
  key    = "vincent-authorizer/deployment.zip"
}

data "aws_s3_object" "vincent_agentcore_zip" {
  bucket = var.lambda_artifacts_bucket
  key    = "vincent-agentcore/deployment.zip"
}

# checksum_sha256 is empty unless the object was uploaded with a SHA256 checksum (see deploy_lambda.sh).
# Fall back to etag so overwrites still trigger Lambda updates.
locals {
  vincent_authorizer_source_hash = coalesce(
    trimspace(replace(data.aws_s3_object.vincent_authorizer_zip.checksum_sha256, "\"", "")),
    trimspace(replace(data.aws_s3_object.vincent_authorizer_zip.etag, "\"", "")),
  )
  vincent_agentcore_source_hash = coalesce(
    trimspace(replace(data.aws_s3_object.vincent_agentcore_zip.checksum_sha256, "\"", "")),
    trimspace(replace(data.aws_s3_object.vincent_agentcore_zip.etag, "\"", "")),
  )
}

# --- Authorizer ---

resource "aws_iam_role" "vincent_authorizer" {
  name = "${var.name_prefix}-authorizer"

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

resource "aws_iam_role_policy_attachment" "vincent_authorizer_basic" {
  role       = aws_iam_role.vincent_authorizer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "vincent_authorizer" {
  name              = "/aws/lambda/${var.name_prefix}-authorizer"
  retention_in_days = 14
}

resource "aws_lambda_function" "vincent_authorizer" {
  function_name = "${var.name_prefix}-authorizer"
  role          = aws_iam_role.vincent_authorizer.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.14"
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 256

  s3_bucket         = var.lambda_artifacts_bucket
  s3_key            = data.aws_s3_object.vincent_authorizer_zip.key
  source_code_hash  = local.vincent_authorizer_source_hash
  s3_object_version = data.aws_s3_object.vincent_authorizer_zip.version_id != null && data.aws_s3_object.vincent_authorizer_zip.version_id != "" ? data.aws_s3_object.vincent_authorizer_zip.version_id : null

  environment {
    variables = {
      GOOGLE_CHAT_AUTH_MODE = var.google_chat_auth_mode
      GOOGLE_CHAT_AUDIENCE  = local.google_chat_audience
    }
  }

  depends_on = [aws_cloudwatch_log_group.vincent_authorizer]
}

# --- AgentCore bridge ---

resource "aws_iam_role" "vincent_agentcore" {
  name = "${var.name_prefix}-agentcore"

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

resource "aws_iam_role_policy_attachment" "vincent_agentcore_basic" {
  role       = aws_iam_role.vincent_agentcore.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "vincent_agentcore_invoke" {
  statement {
    sid    = "InvokeAgentRuntime"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeAgentRuntime",
    ]
    resources = [
      aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn,
      "${aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn}/*",
      aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn,
      "${aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "vincent_agentcore_invoke" {
  name   = "${var.name_prefix}-agentcore-invoke"
  role   = aws_iam_role.vincent_agentcore.id
  policy = data.aws_iam_policy_document.vincent_agentcore_invoke.json
}

resource "aws_cloudwatch_log_group" "vincent_agentcore" {
  name              = "/aws/lambda/${var.name_prefix}-agentcore"
  retention_in_days = 14
}

resource "aws_lambda_function" "vincent_agentcore" {
  function_name = "${var.name_prefix}-agentcore"
  role          = aws_iam_role.vincent_agentcore.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.14"
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 512

  s3_bucket         = var.lambda_artifacts_bucket
  s3_key            = data.aws_s3_object.vincent_agentcore_zip.key
  source_code_hash  = local.vincent_agentcore_source_hash
  s3_object_version = data.aws_s3_object.vincent_agentcore_zip.version_id != null && data.aws_s3_object.vincent_agentcore_zip.version_id != "" ? data.aws_s3_object.vincent_agentcore_zip.version_id : null

  environment {
    variables = {
      AGENT_RUNTIME_ARN                = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
      AGENT_RUNTIME_ENDPOINT_QUALIFIER = aws_bedrockagentcore_agent_runtime_endpoint.main.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.vincent_agentcore,
    aws_iam_role_policy.vincent_agentcore_invoke,
  ]
}
