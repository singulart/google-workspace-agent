# Amazon Bedrock AgentCore requires linux/arm64. Build with:
#   docker build --platform linux/arm64 -t vincent-agent:latest .
# Push to ECR (see terraform output ecr_repository_url).

FROM python:3.13-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_PROPAGATORS=xray \
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false \
    OTEL_TRACES_EXPORTER=otlp \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    OTEL_RESOURCE_ATTRIBUTES=service.name=vincent_agent

COPY agent/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY agent/ .

EXPOSE 8080

# ADOT auto-instrumentation; runtime env sets aws_distro + AgentCore export.
# BedrockAgentCoreApp serves /ping and /invocations (AgentCore HTTP contract).
CMD ["opentelemetry-instrument", "python", "main.py"]
