"""ADOT / OpenTelemetry helpers for the AgentCore runtime container."""

from __future__ import annotations

import logging
import os

from opentelemetry import trace

logger = logging.getLogger(__name__)


def configure_observability() -> None:
    """
    Log observability status at process start.

    Export is configured by ``opentelemetry-instrument`` (Docker CMD) plus runtime
    env vars (``AGENT_OBSERVABILITY_ENABLED``, ``OTEL_PYTHON_DISTRO``, etc.).
    Strands reads the global tracer provider ADOT installs; do not call
    ``StrandsTelemetry()`` here—that would replace ADOT's provider.
    """
    enabled = os.environ.get("AGENT_OBSERVABILITY_ENABLED", "").strip().lower() == "true"
    if not enabled:
        logger.warning(
            "AGENT_OBSERVABILITY_ENABLED is not true; no spans will be exported"
        )
        return

    provider = trace.get_tracer_provider()
    logger.info(
        "observability enabled service=%s tracer_provider=%s",
        _service_name(),
        type(provider).__name__,
    )


def _service_name() -> str:
    for part in os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(","):
        part = part.strip()
        if part.startswith("service.name="):
            return part.split("=", 1)[1]
    return os.environ.get("OTEL_SERVICE_NAME", "unknown")


def trace_attributes_for_invocation(*, session_id: str, actor_id: str) -> dict[str, str]:
    """Custom span attributes for a single AgentCore invocation."""
    return {
        "session.id": session_id,
        "user.id": actor_id,
    }
