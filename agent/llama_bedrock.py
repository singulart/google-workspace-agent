"""Bedrock Llama helpers: text JSON tool calls → native toolUse blocks.

Meta Llama models on the Converse API often return tool invocations as plain text:

    {"type": "function", "name": "my_tool", "parameters": {...}}

with Bedrock ``stopReason`` ``end_turn`` instead of structured ``toolUse`` content
and ``stopReason`` ``tool_use``.

The Strands agent loop only runs tools when the assembled assistant message
contains ``toolUse`` blocks (and the stop reason is treated as ``tool_use``).
If the model puts the call in a ``text`` block instead, the loop ends and the
JSON string is treated as the final reply.

``LlamaToolCallBedrockModel`` rewrites those text blocks into ``toolUse`` blocks
before Strands processes the non-streaming Converse response.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any

from strands.models import BedrockModel
from strands.types.streaming import StreamEvent

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


def _new_tool_use_id() -> str:
    return f"tooluse_{uuid.uuid4().hex}"


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None

    candidates = [stripped]
    fence = _JSON_FENCE_RE.match(stripped)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    return None


def parse_llama_text_tool_call(text: str) -> dict[str, Any] | None:
    """
    Parse Llama's JSON-in-text function call format.

    Returns ``{"name": str, "input": dict}`` or None if the text is not a tool call.
    """
    payload = _try_parse_json_object(text)
    if not payload:
        return None

    if payload.get("type") != "function":
        return None

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    raw_input = payload.get("parameters")
    if raw_input is None:
        raw_input = payload.get("arguments")
    if raw_input is None:
        raw_input = {}
    if not isinstance(raw_input, dict):
        return None

    return {"name": name.strip(), "input": raw_input}


def normalize_llama_tool_calls_in_message_content(content: list[Any]) -> bool:
    """
    Replace text blocks that encode Llama tool calls with Bedrock ``toolUse`` blocks.

    Mutates ``content`` in place. Returns True if any block was converted.
    """
    if not content:
        return False

    changed = False
    normalized: list[Any] = []

    for block in content:
        if not isinstance(block, dict):
            normalized.append(block)
            continue

        if "toolUse" in block:
            normalized.append(block)
            continue

        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            normalized.append(block)
            continue

        parsed = parse_llama_text_tool_call(text)
        if parsed is None:
            normalized.append(block)
            continue

        normalized.append(
            {
                "toolUse": {
                    "toolUseId": _new_tool_use_id(),
                    "name": parsed["name"],
                    "input": parsed["input"],
                }
            }
        )
        changed = True
        logger.info("Converted Llama text tool call to toolUse name=%s", parsed["name"])

    if changed:
        content[:] = normalized
    return changed


class LlamaToolCallBedrockModel(BedrockModel):
    """BedrockModel that normalizes Llama text-encoded tool calls (non-streaming)."""

    def _convert_non_streaming_to_streaming(self, response: dict[str, Any]) -> Iterable[StreamEvent]:
        try:
            content = response["output"]["message"]["content"]
            if isinstance(content, list):
                normalize_llama_tool_calls_in_message_content(content)
        except (KeyError, TypeError):
            logger.debug("Skipping Llama tool-call normalization; unexpected response shape")

        yield from super()._convert_non_streaming_to_streaming(response)
