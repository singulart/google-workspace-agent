output "ecr_repository_url" {
  description = "Push an ARM64 image here before the runtime can start successfully."
  value       = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_id" {
  value = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
}

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

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "sessions_table" {
  value = aws_dynamodb_table.sessions.name
}

output "vpc_subnet_ids" {
  value = data.aws_subnets.default_per_az.ids
}
