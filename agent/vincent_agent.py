"""Strands agent factory for Vincent (Bedrock + optional AgentCore Memory + Gmail MCP)."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from strands_tools.current_time import current_time

from chat_format import format_text_for_google_chat
from telemetry import trace_attributes_for_invocation

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are Vincent, a helpful assistant in Google Chat for a personal Gmail / Workspace user.

Answer clearly and concisely. Every user-visible reply MUST use Google Chat text markup (not GitHub \
Markdown):
- Bold: *word* only (never **word**)
- Italic: _word_
- Strikethrough: ~word~
- Code: `snippet`
- Links: <https://example.com|label> (never [label](url))
- No # headings, no markdown tables, no bullet syntax unless listing (use "- item" at line start)

When you cannot complete a Gmail action (no tools connected or a tool failed), say so plainly \
rather than inventing email contents or results.

Gmail read workflow (two phases — always follow for reading mail):
1. *Discover*: call ``search_threads`` with a Gmail query to get candidate thread IDs. \
``search_threads`` returns ``id`` and ``snippet`` per thread (no ``messages`` array) — use \
``get_threads`` for per-message headers and bodies.
2. *Triage*: pick which thread IDs are likely relevant from the user's question and the list \
size; do not assume you have read message content until phase 3.
3. *Hydrate*: call ``get_threads`` with the chosen ``threadIds`` (or ``get_thread`` for a \
single id). Hydrated messages use a plain-text ``body`` field only (no ``messageFormat`` switch).
4. If ``meta.truncated`` is true or messages have ``omittedFromThread``, tell the user content \
was shortened or omitted and what you might be missing.
5. Keep ``get_threads`` batches small ( up to 10 thread IDs per call unless you know the limit was \
raised). Server caps do not include conversation memory already in the session — avoid \
hydrating large id lists in one turn.
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


def _vincent_tools() -> list[Any]:
    tools: list[Any] = [current_time]
    if _GMAIL_MCP_CLIENT is not None:
        tools.append(_GMAIL_MCP_CLIENT)
    return tools


def _conversation_manager() -> SlidingWindowConversationManager:
    return SlidingWindowConversationManager(
        window_size=100,
        proactive_compression=True,
    )


def _bedrock_streaming_enabled(model_id: str) -> bool:
    """Bedrock ConverseStream does not support tool use for some models (e.g. Llama)."""
    raw = os.environ.get("BEDROCK_STREAMING", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if "llama" in model_id.lower():
        return False
    return True


def _bedrock_model() -> BedrockModel:
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    streaming = _bedrock_streaming_enabled(model_id)
    logger.info("Bedrock model_id=%s streaming=%s", model_id, streaming)
    return BedrockModel(
        model_id=model_id,
        region_name=region,
        temperature=float(os.environ.get("BEDROCK_TEMPERATURE", "0.3")),
        streaming=streaming,
    )


def create_vincent_agent(*, session_id: str, actor_id: str) -> Agent:
    """
    Build a Strands agent for one AgentCore invocation.

    When MEMORY_ID is set on the runtime, conversation history is persisted via
    AgentCoreMemorySessionManager (see AWS sample AGENTCORE.md).

    Includes the built-in ``current_time`` tool (``strands-agents-tools``; optional
    ``DEFAULT_TIMEZONE`` env, default UTC).

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
        "conversation_manager": _conversation_manager(),
        "session_manager": session_manager,
        "callback_handler": None,
        "trace_attributes": trace_attributes_for_invocation(
            session_id=session_id,
            actor_id=actor_id,
        ),
    }
    agent_kwargs["tools"] = _vincent_tools()
    try:
        agent = Agent(**agent_kwargs)
    except ValueError as exc:
        if "Failed to load tool" not in str(exc):
            raise
        logger.warning("Gmail MCP tools unavailable, continuing without: %s", exc)
        agent_kwargs["tools"] = [current_time]
        agent = Agent(**agent_kwargs)
    logger.info("Vincent tools registered: %s", agent.tool_names)
    return agent


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
    raw = assistant_text(result) or "I couldn't generate a reply."
    return format_text_for_google_chat(raw)
