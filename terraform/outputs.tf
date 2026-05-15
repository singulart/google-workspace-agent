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