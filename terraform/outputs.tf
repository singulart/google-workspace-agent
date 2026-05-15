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
  description = "Set as the Chat app HTTPS endpoint URL in Google Cloud Console."
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