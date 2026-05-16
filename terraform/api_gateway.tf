# Regional REST API: POST /v1/vincent (Google Chat) -> vincent-agentcore
# TOKEN authorizer: vincent-authorizer (Google Chat Bearer JWT)

locals {
  api_redeployment_hash = sha1(jsonencode([
    aws_api_gateway_resource.v1.id,
    aws_api_gateway_resource.vincent.id,
    aws_api_gateway_method.vincent_post.id,
    aws_api_gateway_integration.vincent_post.id,
    aws_api_gateway_authorizer.vincent.id,
    aws_lambda_function.vincent_authorizer.source_code_hash,
    aws_lambda_function.vincent_agentcore.source_code_hash,
  ]))
}

resource "aws_api_gateway_rest_api" "vincent" {
  name        = "${var.name_prefix}-chat-api"
  description = "Google Chat HTTPS endpoint for Vincent"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "v1" {
  rest_api_id = aws_api_gateway_rest_api.vincent.id
  parent_id   = aws_api_gateway_rest_api.vincent.root_resource_id
  path_part   = "v1"
}

resource "aws_api_gateway_resource" "vincent" {
  rest_api_id = aws_api_gateway_rest_api.vincent.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "vincent"
}

resource "aws_api_gateway_authorizer" "vincent" {
  name                             = "vincent-authorizer"
  rest_api_id                      = aws_api_gateway_rest_api.vincent.id
  type                             = "TOKEN"
  authorizer_uri                   = aws_lambda_function.vincent_authorizer.invoke_arn
  identity_source                  = "method.request.header.Authorization"
  authorizer_result_ttl_in_seconds = 300
}

resource "aws_lambda_permission" "vincent_authorizer_apigw" {
  statement_id  = "AllowCallingAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vincent_authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  # REST API authorizer invokes use .../authorizers/{authorizerId} (not */* or authorizers/*).
  source_arn = "${aws_api_gateway_rest_api.vincent.execution_arn}/*/*"
}

resource "aws_api_gateway_method" "vincent_post" {
  rest_api_id   = aws_api_gateway_rest_api.vincent.id
  resource_id   = aws_api_gateway_resource.vincent.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.vincent.id

  request_parameters = {
    "method.request.header.Authorization" = true
  }
}

resource "aws_api_gateway_integration" "vincent_post" {
  rest_api_id             = aws_api_gateway_rest_api.vincent.id
  resource_id             = aws_api_gateway_resource.vincent.id
  http_method             = aws_api_gateway_method.vincent_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.vincent_agentcore.invoke_arn
}

resource "aws_lambda_permission" "vincent_agentcore_apigw" {
  statement_id  = "AllowAPIGatewayInvokeAgentcore"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vincent_agentcore.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.vincent.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "vincent" {
  rest_api_id = aws_api_gateway_rest_api.vincent.id

  triggers = {
    redeployment = local.api_redeployment_hash
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.vincent_post,
    aws_lambda_permission.vincent_authorizer_apigw,
    aws_lambda_permission.vincent_agentcore_apigw,
  ]
}

resource "aws_api_gateway_stage" "vincent" {
  rest_api_id   = aws_api_gateway_rest_api.vincent.id
  deployment_id = aws_api_gateway_deployment.vincent.id
  stage_name    = var.api_gateway_stage_name

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_access.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      caller         = "$context.identity.caller"
      user           = "$context.identity.user"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      resourcePath   = "$context.resourcePath"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      errorMessage   = "$context.error.message"
    })
  }

  depends_on = [aws_api_gateway_account.vincent]
}

resource "aws_cloudwatch_log_group" "api_gateway_access" {
  name              = "/aws/apigateway/${var.name_prefix}-chat-api"
  retention_in_days = 14
}

resource "aws_iam_role" "api_gateway_cloudwatch" {
  name = "${var.name_prefix}-apigw-cloudwatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "vincent" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn
}

resource "aws_api_gateway_method_settings" "vincent" {
  rest_api_id = aws_api_gateway_rest_api.vincent.id
  stage_name  = aws_api_gateway_stage.vincent.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled    = true
    logging_level      = "INFO"
    data_trace_enabled = false
  }
}

# Lambda GOOGLE_CHAT_AUDIENCE cannot reference stage.invoke_url (Terraform cycle: stage →
# deployment → integration → Lambda). locals.google_chat_webhook_url is the same string AWS
# uses for invoke_url; this check fails the plan/apply if that ever diverges.
check "google_chat_url_matches_stage_invoke_url" {
  assert {
    condition = (
      trimsuffix(aws_api_gateway_stage.vincent.invoke_url, "/") ==
      trimsuffix(local.google_chat_webhook_url, "/v1/vincent")
    )
    error_message = "locals.google_chat_webhook_url base must equal aws_api_gateway_stage.invoke_url (trimmed); update locals.tf if AWS URL format changes."
  }
}
