locals {
  gmail_mcp_runtime_encoded_arn = replace(
    replace(aws_bedrockagentcore_agent_runtime.gmail_mcp.agent_runtime_arn, ":", "%3A"),
    "/",
    "%2F",
  )
  gmail_mcp_mcp_invoke_url = "https://bedrock-agentcore.${data.aws_region.current.id}.amazonaws.com/runtimes/${local.gmail_mcp_runtime_encoded_arn}/invocations?qualifier=${aws_bedrockagentcore_agent_runtime_endpoint.gmail_mcp.name}"

  # Must match aws_api_gateway_stage.vincent.invoke_url (see check block in api_gateway.tf).
  # Built from rest API id + region + stage only — cannot use stage.invoke_url in Lambda env
  # because of a Terraform cycle: stage → deployment → integration → Lambda → env → stage.
  google_chat_webhook_url = "https://${aws_api_gateway_rest_api.vincent.id}.execute-api.${data.aws_region.current.id}.amazonaws.com/${var.api_gateway_stage_name}/v1/vincent"

  # Authorizer GOOGLE_CHAT_AUDIENCE: project number, or full URL (default = webhook URL above).
  google_chat_audience = var.google_chat_auth_mode == "http_url" ? (
    trimspace(var.google_chat_http_audience) != "" ? var.google_chat_http_audience : local.google_chat_webhook_url
  ) : var.google_chat_project_number
}
