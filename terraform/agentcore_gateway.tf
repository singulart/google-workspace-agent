# MCP gateway (inbound AWS_IAM) -> MCP server target -> gmail_mcp AgentCore Runtime (outbound IAM / SigV4).

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
    sid    = "InvokeGmailMcpRuntime"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeAgentRuntime",
    ]
    resources = [
      aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn,
      "${aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn}/*",
    ]
  }

  statement {
    sid    = "SynchronizeGatewayTargets"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:SynchronizeGatewayTargets",
    ]
    resources = [
      aws_bedrockagentcore_gateway.gmail_mcp.gateway_arn,
    ]
  }
}

resource "aws_iam_role_policy" "agentcore_gateway" {
  name   = "${var.name_prefix}-agentcore-gateway"
  role   = aws_iam_role.agentcore_gateway.id
  policy = data.aws_iam_policy_document.agentcore_gateway_inline.json
}

resource "aws_bedrockagentcore_gateway" "gmail_mcp" {
  name            = "${var.name_prefix}-gmail-mcp"
  description     = "MCP gateway for Gmail tools (catalog from gmail_mcp runtime)."
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
#   credential_provider_configuration {
#     gateway_iam_role {
#       service = "bedrock-agentcore"
#       region  = data.aws_region.current.id
#     }
#   }
locals {
  gmail_mcp_gateway_target_template = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Parameters = {
      GatewayIdentifier = { Type = "String" }
      McpEndpoint       = { Type = "String" }
      AwsRegion         = { Type = "String" }
    }
    Resources = {
      GmailMcpRuntimeTarget = {
        Type = "AWS::BedrockAgentCore::GatewayTarget"
        Properties = {
          GatewayIdentifier = { Ref = "GatewayIdentifier" }
          Name              = "gmail-mcp"
          Description       = "Gmail MCP server on AgentCore Runtime"
          CredentialProviderConfigurations = [{
            CredentialProviderType = "GATEWAY_IAM_ROLE"
            CredentialProvider = {
              IamCredentialProvider = {
                Service = "bedrock-agentcore"
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
            AllowedRequestHeaders  = ["Mcp-Session-Id"]
            AllowedResponseHeaders = ["Mcp-Session-Id"]
          }
        }
      }
    }
    Outputs = {
      TargetId = {
        Value = { "Fn::GetAtt" = ["GmailMcpRuntimeTarget", "TargetId"] }
      }
    }
  })
}

resource "aws_cloudformation_stack" "gmail_mcp_gateway_target" {
  name          = "${var.name_prefix}-gmail-mcp-gateway-target"
  template_body = local.gmail_mcp_gateway_target_template

  parameters = {
    GatewayIdentifier = aws_bedrockagentcore_gateway.gmail_mcp.gateway_id
    McpEndpoint       = local.gmail_mcp_mcp_invoke_url
    AwsRegion         = data.aws_region.current.id
  }

  depends_on = [
    aws_iam_role_policy.agentcore_gateway,
    aws_bedrockagentcore_agent_runtime_endpoint.gmail_mcp,
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

output "gmail_mcp_gateway_id" {
  description = "AgentCore gateway ID for Gmail MCP tool catalog."
  value       = aws_bedrockagentcore_gateway.gmail_mcp.gateway_id
}

output "gmail_mcp_gateway_url" {
  description = "MCP URL for clients (SigV4 InvokeGateway)."
  value       = aws_bedrockagentcore_gateway.gmail_mcp.gateway_url
}

output "gmail_mcp_gateway_target_id" {
  description = "Gateway target ID (use with synchronize-gateway-targets after tool changes)."
  value       = aws_cloudformation_stack.gmail_mcp_gateway_target.outputs["TargetId"]
}