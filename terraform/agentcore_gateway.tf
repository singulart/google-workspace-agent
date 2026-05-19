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
  # Function URL with AWS_IAM requires both actions on the caller identity policy.
  # https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html
  statement {
    sid    = "InvokeGmailDwdMcpFunctionUrl"
    effect = "Allow"
    actions = [
      "lambda:InvokeFunctionUrl",
      "lambda:InvokeFunction",
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

# MCP server targets with IAM outbound auth require IamCredentialProvider { service, region? }.
# aws_bedrockagentcore_gateway_target.gateway_iam_role {} does not send that body yet
# (https://github.com/hashicorp/terraform-provider-aws/issues/47628). Use CloudFormation
# until provider >= merge of https://github.com/hashicorp/terraform-provider-aws/pull/47626.
#
# Then replace this stack with:
#   credential_provider_configuration { gateway_iam_role { service = "lambda" } }
locals {
  gmail_dwd_mcp_gateway_target_template = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Parameters = {
      GatewayIdentifier = { Type = "String" }
      McpEndpoint       = { Type = "String" }
      AwsRegion         = { Type = "String" }
    }
    Resources = {
      GmailDwdMcpTarget = {
        Type = "AWS::BedrockAgentCore::GatewayTarget"
        Properties = {
          GatewayIdentifier = { Ref = "GatewayIdentifier" }
          Name              = "gmail-mcp"
          Description       = "Gmail MCP server on Lambda"
          CredentialProviderConfigurations = [{
            CredentialProviderType = "GATEWAY_IAM_ROLE"
            CredentialProvider = {
              IamCredentialProvider = {
                Service = "lambda"
                Region  = { Ref = "AwsRegion" }
              }
            }
          }]
          TargetConfiguration = {
            Mcp = {
              McpServer = {
                Endpoint = { Ref = "McpEndpoint" }
              }
            }
          }
          MetadataConfiguration = {
            AllowedRequestHeaders  = ["mcp-session-id"]
            AllowedResponseHeaders = ["mcp-session-id"]
          }
        }
      }
    }
    Outputs = {
      TargetId = {
        Value = { "Fn::GetAtt" = ["GmailDwdMcpTarget", "TargetId"] }
      }
    }
  })
}

resource "aws_cloudformation_stack" "gmail_gateway_target" {
  name          = "${var.name_prefix}-gmail-gateway-target"
  template_body = local.gmail_dwd_mcp_gateway_target_template

  parameters = {
    GatewayIdentifier = aws_bedrockagentcore_gateway.gmail_mcp.gateway_id
    McpEndpoint       = "${aws_lambda_function_url.gmail_dwd_mcp.function_url}/mcp"
    AwsRegion         = data.aws_region.current.id
  }

  depends_on = [
    aws_lambda_permission.gmail_dwd_mcp_gateway_function_url,
    aws_lambda_permission.gmail_dwd_mcp_gateway_invoke_function,
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
