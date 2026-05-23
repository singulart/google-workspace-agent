FROM python:3.13-slim-bookworm AS builder

WORKDIR /build

COPY agent/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt -t /deps \
    && find /deps/bin -type f -exec sed -i 's|#!/usr/local/bin/python3.13|#!/usr/bin/python3.13|g' {} +

FROM gcr.io/distroless/python3

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/deps \
    AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_PROPAGATORS=xray \
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false \
    OTEL_TRACES_EXPORTER=otlp \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    OTEL_RESOURCE_ATTRIBUTES=service.name=vincent_agent \
    OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental,gen_ai_tool_definitions \
    OTEL_TRACES_SAMPLER=always_on \ 
    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=false

COPY --from=builder /deps /deps
COPY agent/ .

EXPOSE 8080

CMD ["/deps/bin/opentelemetry-instrument", "python", "main.py"]
