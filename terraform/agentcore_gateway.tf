# AgentCore Gateway (inbound AWS_IAM) -> MCP server target -> gmail-dwd-mcp Lambda Function URL (outbound IAM).

data "aws_iam_policy_document" "agentcore_gateway_assume" {
  statement {
    sid    = "GatewayAssumeRolePolicy"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
    ]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:gateway/${var.name_prefix}-gmail-mcp*",
      ]
    }
  }
}

resource "aws_iam_role" "agentcore_gateway" {
  name               = "${var.name_prefix}-agentcore-gateway"
  assume_role_policy = data.aws_iam_policy_document.agentcore_gateway_assume.json
}

data "aws_iam_policy_document" "agentcore_gateway_inline" {
  statement {
    sid    = "InvokeGmailDwdMcpFunctionUrl"
    effect = "Allow"
    actions = [
      "lambda:InvokeFunctionUrl",
    ]
    resources = [aws_lambda_function.gmail_dwd_mcp.arn]
  }
}

resource "aws_iam_role_policy" "agentcore_gateway" {
  name   = "${var.name_prefix}-agentcore-gateway"
  role   = aws_iam_role.agentcore_gateway.id
  policy = data.aws_iam_policy_document.agentcore_gateway_inline.json
}

resource "aws_bedrockagentcore_gateway" "gmail_mcp" {
  name            = "${var.name_prefix}-gmail-mcp"
  description     = "MCP gateway for Gmail tools."
  role_arn        = aws_iam_role.agentcore_gateway.arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"

  protocol_configuration {
    mcp {
      supported_versions = ["2025-03-26", "2025-06-18"]
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "gmail_dwd_mcp" {
  name               = "gmail-dwd-mcp"
  gateway_identifier = aws_bedrockagentcore_gateway.gmail_mcp.gateway_id
  description        = "FastMCP server on Lambda"

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint = aws_lambda_function_url.gmail_dwd_mcp.function_url
      }
    }
  }

  metadata_configuration {
    allowed_request_headers  = ["mcp-session-id"]
    allowed_response_headers = ["mcp-session-id"]
  }

  depends_on = [
    aws_lambda_permission.gmail_dwd_mcp_gateway_function_url,
    aws_iam_role_policy.agentcore_gateway,
  ]
}

# Vincent AgentCore runtime may call the gateway MCP endpoint (SigV4 inbound).
data "aws_iam_policy_document" "agent_runtime_invoke_gateway" {
  statement {
    sid    = "InvokeGmailMcpGateway"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeGateway",
    ]
    resources = [
      aws_bedrockagentcore_gateway.gmail_mcp.gateway_arn,
    ]
  }
}

resource "aws_iam_role_policy" "agent_runtime_invoke_gateway" {
  name   = "${var.name_prefix}-agentcore-runtime-invoke-gateway"
  role   = aws_iam_role.agent_runtime.id
  policy = data.aws_iam_policy_document.agent_runtime_invoke_gateway.json
}
