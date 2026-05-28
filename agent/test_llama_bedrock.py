"""Tests for Llama Bedrock text tool-call normalization."""

from __future__ import annotations

import json

from llama_bedrock import (
    normalize_llama_tool_calls_in_message_content,
    parse_llama_text_tool_call,
)


def test_parse_llama_text_tool_call_user_example() -> None:
    text = json.dumps(
        {
            "type": "function",
            "name": "gmail-mcp___search_threads",
            "parameters": {
                "pageSize": "10",
                "email": "abc@def.com",
                "query": "from:me in:sent after:2024/03/01 before:2024/03/31",
                "includeTrash": "false",
            },
        }
    )
    parsed = parse_llama_text_tool_call(text)
    assert parsed is not None
    assert parsed["name"] == "gmail-mcp___search_threads"
    assert parsed["input"]["query"].startswith("from:me")


def test_parse_llama_text_tool_call_ignores_plain_text() -> None:
    assert parse_llama_text_tool_call("Here are your emails.") is None


def test_normalize_replaces_text_with_tool_use() -> None:
    text = json.dumps({"type": "function", "name": "roll_die", "parameters": {}})
    content = [{"text": text}]
    assert normalize_llama_tool_calls_in_message_content(content) is True
    assert len(content) == 1
    assert "toolUse" in content[0]
    assert content[0]["toolUse"]["name"] == "roll_die"
    assert content[0]["toolUse"]["toolUseId"].startswith("tooluse_")


def test_normalize_leaves_non_tool_json_text() -> None:
    content = [{"text": '{"status": "ok"}'}]
    assert normalize_llama_tool_calls_in_message_content(content) is False
    assert content == [{"text": '{"status": "ok"}'}]
