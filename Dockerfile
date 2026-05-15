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

# Use plain uvicorn so the process binds quickly. `opentelemetry-instrument` + ADOT
# can exceed AgentCore's ~120s runtime initialization budget (cold start + OTLP setup).
# Re-introduce OTEL after Transaction Search/destinations are ACTIVE if you need ADOT.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
