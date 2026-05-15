"""Greeting detection and reply text for Google Chat + AgentCore /invocations."""

from __future__ import annotations

import re
from typing import Any

# User-visible "hello" style greetings (substring match after normalization).
_GREETING_RE = re.compile(
    r"\b("
    r"hello\b|hi\b|hey\b|howdy\b|good\s+(morning|afternoon|evening)\b|greetings\b"
    r")\b",
    re.IGNORECASE,
)

# Strip Chat user mentions like <users/123456789012345678901> from visible text.
_MENTION_RE = re.compile(r"<users/[^>]+>")


def strip_chat_mentions(text: str) -> str:
    t = _MENTION_RE.sub("", text)
    return " ".join(t.split())


def is_greeting(text: str) -> bool:
    if not text or not text.strip():
        return False
    normalized = strip_chat_mentions(text).strip()
    return bool(_GREETING_RE.search(normalized))


def greeting_reply() -> str:
    return "Hello — Vincent here. Nice to see you in Chat."


def extract_user_text_from_chat_event(event: dict[str, Any]) -> str | None:
    """
    Best-effort extraction of what the user typed for a MESSAGE-style Chat event.
    Supports both legacy `type` and API `eventType` fields.
    """
    kind = event.get("eventType") or event.get("type")
    if kind != "MESSAGE":
        return None
    msg = event.get("message")
    if not isinstance(msg, dict):
        return None
    # Slash commands often populate argumentText; plain messages use text.
    raw = (
        msg.get("argumentText")
        or msg.get("text")
        or msg.get("formattedText")
        or ""
    ).strip()
    return raw or None


def extract_prompt_from_body(body: dict[str, Any]) -> str | None:
    """AgentCore sample contract uses top-level `prompt` (string)."""
    p = body.get("prompt")
    if isinstance(p, str) and p.strip():
        return p
    return None


def process_invocation_body(body: dict[str, Any]) -> dict[str, Any]:
    """
    Returns a dict suitable for JSONResponse: AgentCore `response` + `status`,
    plus optional metadata. Google Chat synchronous replies use `text` at the
    top level — if your HTTPS Chat endpoint is this same app, return Chat shape
    instead (see app.py); for AgentCore always use response/status.
    """
    prompt = extract_prompt_from_body(body)
    if prompt is not None:
        if is_greeting(prompt):
            text = greeting_reply()
            return {"response": text, "status": "success", "source": "prompt"}
        return {
            "response": "Ask me with a greeting like “Hello” and I will reply.",
            "status": "success",
            "source": "prompt",
        }

    chat_text = extract_user_text_from_chat_event(body)
    if chat_text is not None:
        if is_greeting(chat_text):
            text = greeting_reply()
            return {"response": text, "status": "success", "source": "google_chat_message"}
        return {
            "response": "For now I only chime in on simple greetings—try saying Hello.",
            "status": "success",
            "source": "google_chat_message",
        }

    kind = body.get("eventType") or body.get("type")
    if kind:
        return {
            "response": "",
            "status": "success",
            "ignored_event": kind,
        }

    return {
        "response": "Send {\"prompt\": \"Hello\"} or a Google Chat interaction event JSON.",
        "status": "success",
        "source": "unknown_payload",
    }
