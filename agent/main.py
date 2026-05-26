"""
Vincent on Amazon Bedrock AgentCore Runtime.

Uses the official BedrockAgentCoreApp wrapper (Strands + Bedrock). AgentCore provides
/ping and /invocations; do not add a custom Starlette/FastAPI server for those routes.

Google Chat reaches this runtime via the vincent-agentcore Lambda bridge.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

from chat_google import try_post_chat_message
from chat_payload import delivery_from_payload, extract_invocation_input
from telemetry import configure_observability
from vincent_agent import create_vincent_agent, run_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

configure_observability()

app = BedrockAgentCoreApp()

# Grep runtime APPLICATION_LOGS for this line to confirm the deployed image includes your build.
logger.info("vincent runtime loaded (xml_user_message=1)")


def _run_agent_and_post_chat(
    *,
    session_id: str,
    actor_id: str,
    user_message: str,
    delivery: dict[str, Any],
) -> None:
    agent = create_vincent_agent(session_id=session_id, actor_id=actor_id)
    text = run_agent(agent, user_message)
    posted = try_post_chat_message(delivery, text)
    logger.info("chat reply posted=%s len=%s", posted, len(text))


def _schedule_chat_reply(
    *,
    session_id: str,
    actor_id: str,
    user_message: str,
    delivery: dict[str, Any],
    source: str,
) -> str:
    """Run agent + Chat API post in a background thread; return immediately."""
    task_id = app.add_async_task(
        "chat_message",
        {"source": source, "session_id": session_id},
    )

    def background_work() -> None:
        try:
            _run_agent_and_post_chat(
                session_id=session_id,
                actor_id=actor_id,
                user_message=user_message,
                delivery=delivery,
            )
        except Exception:
            logger.exception("background chat_message failed session_id=%s", session_id)
        finally:
            app.complete_async_task(task_id)

    threading.Thread(target=background_work, daemon=True).start()
    return task_id


@app.entrypoint
def invoke(payload: dict, context: RequestContext) -> dict:
    """
    AgentCore entrypoint. Payload is the JSON body from InvokeAgentRuntime
    (Google Chat event envelope from the Lambda proxy, or {"prompt": "..."} for tests).

    When ``_delivery`` is present (Google Chat), the agent runs in a background thread
    so InvokeAgentRuntime returns quickly; the reply is posted via spaces.messages.create.
    Prompt-only invocations without delivery still run synchronously for local testing.
    """
    if not isinstance(payload, dict):
        return {"response": "Expected a JSON object body.", "status": "error"}

    invocation = extract_invocation_input(payload)
    if invocation is None:
        kind = payload.get("eventType") or payload.get("type") or "unknown"
        logger.info("ignored_event kind=%s", kind)
        return {"response": "", "status": "success", "ignored_event": kind}

    session_id = (context.session_id or "").strip() or f"session-{uuid.uuid4()}"
    logger.info(
        "invoke source=%s session_id=%s actor_id=%s user_message=%.200s",
        invocation.source,
        session_id,
        invocation.actor_id,
        invocation.user_message,
    )

    delivery = delivery_from_payload(payload)

    if delivery:
        task_id = _schedule_chat_reply(
            session_id=session_id,
            actor_id=invocation.actor_id,
            user_message=invocation.user_message,
            delivery=delivery,
            source=invocation.source,
        )
        return {
            "response": "",
            "status": "accepted",
            "source": invocation.source,
            "async_task_id": task_id,
        }

    agent = create_vincent_agent(session_id=session_id, actor_id=invocation.actor_id)
    text = run_agent(agent, invocation.user_message)

    return {
        "response": text,
        "status": "success",
        "source": invocation.source,
        "chat_posted": False,
    }


if __name__ == "__main__":
    app.run()
