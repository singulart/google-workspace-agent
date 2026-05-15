# Amazon Bedrock AgentCore requires linux/arm64. Build with:
#   docker build --platform linux/arm64 -t vincent-agent:latest .
# Push to ECR (see terraform output ecr_repository_url).

FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY agent/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY agent/ .

EXPOSE 8080

# ADOT auto-instrumentation → CloudWatch (GenAI Observability). Requires account
# CloudWatch Transaction Search enabled; see AWS AgentCore observability docs.
CMD ["opentelemetry-instrument", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
