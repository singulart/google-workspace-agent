output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}

output "agent_runtime_endpoint_arn" {
  value = aws_bedrockagentcore_agent_runtime_endpoint.main.agent_runtime_endpoint_arn
}

output "agentcore_memory_id" {
  value       = aws_bedrockagentcore_memory.main.id
  description = "Pass to the AgentCore Memory SDK / session configuration."
}

output "google_chat_webhook_url" {
  value       = local.google_chat_webhook_url
  description = "Full POST URL for Chat (same string as google_chat_auth_audience in http_url default mode)."
}

output "google_chat_stage_invoke_url" {
  value       = aws_api_gateway_stage.vincent.invoke_url
  description = "aws_api_gateway_stage.invoke_url — base URL only (no /v1/vincent); must match prefix of google_chat_webhook_url."
}

output "google_chat_auth_audience" {
  value       = local.google_chat_audience
  description = "Authentication audience to configure in the Chat app (project number or full URL)."
}

output "google_chat_auth_mode" {
  value       = var.google_chat_auth_mode
  description = "Must match Authentication audience type in Chat app configuration."
}

output "api_gateway_id" {
  value = aws_api_gateway_rest_api.vincent.id
}

output "lambda_authorizer_artifact" {
  description = "S3 object fingerprints used for source_code_hash (debug deploy/apply drift)."
  value = {
    checksum_sha256 = data.aws_s3_object.vincent_authorizer_zip.checksum_sha256
    etag            = data.aws_s3_object.vincent_authorizer_zip.etag
    version_id      = data.aws_s3_object.vincent_authorizer_zip.version_id
    source_hash     = local.vincent_authorizer_source_hash
  }
}