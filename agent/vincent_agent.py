"""Strands agent factory for Vincent (Bedrock + optional AgentCore Memory + Gmail MCP)."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are Vincent, a helpful assistant in Google Chat for a personal Gmail / Workspace user.

Answer clearly and concisely in plain text suitable for a chat message (no markdown tables).
Use the MCP tools available to you for Gmail tasks when appropriate.
When describing your capabilities or tool list, only mention tools you actually have from the \
connected MCP server—never invent tool names.
When you cannot complete a Gmail action (no tools connected or a tool failed), say so plainly \
rather than inventing email contents or results.
"""


def _memory_id() -> str | None:
    for key in ("MEMORY_ID", "BEDROCK_AGENTCORE_MEMORY_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _gmail_gateway_url() -> str | None:
    value = os.environ.get("GMAIL_MCP_GATEWAY_URL", "").strip()
    return value or None


def _create_gmail_mcp_client() -> MCPClient | None:
    url = _gmail_gateway_url()
    if not url:
        logger.info("GMAIL_MCP_GATEWAY_URL not set; Gmail MCP tools disabled")
        return None

    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        client = MCPClient(
            lambda endpoint=url, aws_region=region: aws_iam_streamablehttp_client(
                endpoint=endpoint,
                aws_region=aws_region,
                aws_service="bedrock-agentcore",
            )
        )
        logger.info("Gmail MCP client configured for AgentCore gateway")
        return client
    except Exception:
        logger.exception("Failed to create Gmail MCP client")
        return None


_GMAIL_MCP_CLIENT = _create_gmail_mcp_client()


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

    When GMAIL_MCP_GATEWAY_URL is set, Gmail tools are loaded from the AgentCore MCP
    gateway via MCPClient (SigV4 / IAM).
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

    agent_kwargs: dict[str, Any] = {
        "model": _bedrock_model(),
        "system_prompt": _SYSTEM_PROMPT,
        "session_manager": session_manager,
        "callback_handler": None,
    }
    if _GMAIL_MCP_CLIENT is None:
        return Agent(**agent_kwargs)

    agent_kwargs["tools"] = [_GMAIL_MCP_CLIENT]
    try:
        return Agent(**agent_kwargs)
    except ValueError as exc:
        if "Failed to load tool" not in str(exc):
            raise
        logger.warning("Gmail MCP tools unavailable, continuing without: %s", exc)
        del agent_kwargs["tools"]
        return Agent(**agent_kwargs)


def _text_from_content_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            text = block.get("text")
            if text:
                parts.append(str(text))
        elif hasattr(block, "text") and block.text:
            parts.append(str(block.text))
    return "\n".join(parts).strip()


def _text_from_message_dict(message: dict[str, Any]) -> str:
    text = _text_from_content_blocks(message.get("content"))
    if text:
        return text
    nested = message.get("message")
    if isinstance(nested, dict):
        return _text_from_message_dict(nested)
    if isinstance(nested, str):
        return nested.strip()
    return ""


def assistant_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()

    if isinstance(result, dict):
        return _text_from_message_dict(result)

    message = getattr(result, "message", None)
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        return _text_from_message_dict(message)

    for source in (message, result):
        if source is None:
            continue
        content = getattr(source, "content", None)
        text = _text_from_content_blocks(content)
        if text:
            return text

    if message is not None:
        return str(message).strip()
    return str(result).strip()


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
