"""Strands agent factory for Vincent (Bedrock + optional AgentCore Memory)."""

from __future__ import annotations

import logging
import os
from typing import Any

from strands import Agent
from strands.models import BedrockModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are Vincent, a helpful assistant in Google Chat for a personal Gmail / Workspace user.

Answer clearly and concisely in plain text suitable for a chat message (no markdown tables).
When you do not have access to the user's mailbox, say so rather than inventing email contents.
"""


def _memory_id() -> str | None:
    for key in ("MEMORY_ID", "BEDROCK_AGENTCORE_MEMORY_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _bedrock_model() -> BedrockModel:
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    return BedrockModel(
        model_id=model_id,
        region_name=region,
        temperature=float(os.environ.get("BEDROCK_TEMPERATURE", "0.3")),
    )


def create_vincent_agent(*, session_id: str, actor_id: str) -> Agent:
    """
    Build a Strands agent for one AgentCore invocation.

    When MEMORY_ID is set on the runtime, conversation history is persisted via
    AgentCoreMemorySessionManager (see AWS sample AGENTCORE.md).
    """
    session_manager = None
    memory_id = _memory_id()
    region = os.environ.get("AWS_REGION", "us-east-1")

    if memory_id and session_id:
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import (
            AgentCoreMemorySessionManager,
        )

        memory_config = AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=session_id,
            actor_id=actor_id,
        )
        session_manager = AgentCoreMemorySessionManager(memory_config, region)

    return Agent(
        model=_bedrock_model(),
        system_prompt=_SYSTEM_PROMPT,
        session_manager=session_manager,
        callback_handler=None,
    )


def assistant_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()

    message = getattr(result, "message", None)
    if isinstance(message, str):
        return message.strip()
    if message is None:
        return str(result).strip()

    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif hasattr(block, "text") and block.text:
                parts.append(str(block.text))
        if parts:
            return "\n".join(parts).strip()

    return str(message).strip()


def run_agent(agent: Agent, user_message: str) -> str:
    try:
        result = agent(user_message)
    except Exception:
        logger.exception("Strands agent invocation failed")
        return (
            "Something went wrong while processing your message. "
            "Please try again in a moment."
        )
    return assistant_text(result) or "I couldn't generate a reply."
