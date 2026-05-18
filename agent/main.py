"""
Vincent on Amazon Bedrock AgentCore Runtime.

Uses the official BedrockAgentCoreApp wrapper (Strands + Bedrock). AgentCore provides
/ping and /invocations; do not add a custom Starlette/FastAPI server for those routes.

Google Chat reaches this runtime via the vincent-agentcore Lambda bridge.
"""

from __future__ import annotations

import logging
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

from chat_payload import extract_invocation_input
from vincent_agent import create_vincent_agent, run_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, context: RequestContext) -> dict:
    """
    AgentCore entrypoint. Payload is the JSON body from InvokeAgentRuntime
    (Google Chat event envelope from the Lambda proxy, or {"prompt": "..."} for tests).
    """
    if not isinstance(payload, dict):
        return {"response": "Expected a JSON object body.", "status": "error"}

    invocation = extract_invocation_input(payload)
    if invocation is None:
        kind = payload.get("eventType") or payload.get("type") or "unknown"
        return {"response": "", "status": "success", "ignored_event": kind}

    session_id = (context.session_id or "").strip() or f"session-{uuid.uuid4()}"
    logger.info(
        "invoke source=%s session_id=%s actor_id=%s",
        invocation.source,
        session_id,
        invocation.actor_id,
    )

    agent = create_vincent_agent(session_id=session_id, actor_id=invocation.actor_id)
    text = run_agent(agent, invocation.user_message)

    return {
        "response": text,
        "status": "success",
        "source": invocation.source,
    }


if __name__ == "__main__":
    app.run()
