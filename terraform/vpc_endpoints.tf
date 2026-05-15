# Private connectivity for AgentCore runtime ENIs in VPC (no NAT required for these services).
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html#agentcore-vpc-endpoints
#
# S3 gateway endpoint: not managed here (owned by ASAPCV Terraform repo). AgentCore container
# pulls need GetObject on prod-<region>-starport-layer-bucket; the agent needs the uploads
# bucket — add both in that repo's S3 VPC endpoint policy if scoped (see output s3_vpc_endpoint_policy_hints).

resource "aws_security_group" "vpc_interface_endpoints" {
  name        = "${var.name_prefix}-vpc-interface-endpoints"
  description = "HTTPS from AgentCore runtime to interface VPC endpoints"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "HTTPS from AgentCore runtime"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.agent_runtime.id]
  }

  tags = {
    Name = "${var.name_prefix}-vpc-interface-endpoints"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.aws_subnets.agentcore_compatible.ids
  security_group_ids  = [aws_security_group.vpc_interface_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-ecr-api"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.aws_subnets.agentcore_compatible.ids
  security_group_ids  = [aws_security_group.vpc_interface_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-ecr-dkr"
  }
}

resource "aws_vpc_endpoint" "cloudwatch_logs" {
  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.aws_subnets.agentcore_compatible.ids
  security_group_ids  = [aws_security_group.vpc_interface_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-cloudwatch-logs"
  }
}