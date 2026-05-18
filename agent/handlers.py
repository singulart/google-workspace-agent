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


def uses_workspace_addon_http_format(body: dict[str, Any]) -> bool:
    """
    Google routes many HTTP Chat apps through the Workspace add-ons pipeline when
    the request includes add-on EventObject fields (see chat.messagePayload).
    """
    if isinstance(body.get("chat"), dict):
        return True
    if isinstance(body.get("commonEventObject"), dict):
        return True
    if isinstance(body.get("authorizationEventObject"), dict):
        return True
    return False


def format_google_chat_sync_reply(
    text: str,
    request_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Synchronous HTTP reply shape depends on which pipeline handles the request.

    - Classic Chat API interaction events: top-level Message fields, e.g. {"text": "..."}.
    - Workspace add-ons HTTP: hostAppDataAction / createMessageAction wrapper.
      https://developers.google.com/workspace/add-ons/chat/send-messages
    """
    if not text.strip():
        return {}
    if request_body is not None and uses_workspace_addon_http_format(request_body):
        return {
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {
                        "message": {"text": text},
                    },
                },
            },
        }
    return {"text": text}


def _normalize_google_chat_http_event(body: dict[str, Any]) -> dict[str, Any]:
    """
    Workspace Chat HTTP payloads often wrap the message under `chat.messagePayload`
    while also (or only) exposing legacy top-level `message` / `user` / `space`.
    """
    kind = body.get("eventType") or body.get("type")
    if kind == "MESSAGE" and isinstance(body.get("message"), dict):
        return body

    chat = body.get("chat")
    if not isinstance(chat, dict):
        return body
    mp = chat.get("messagePayload")
    if not isinstance(mp, dict):
        return body
    message = mp.get("message")
    if not isinstance(message, dict):
        return body

    user = chat.get("user") if isinstance(chat.get("user"), dict) else {}
    space = mp.get("space") if isinstance(mp.get("space"), dict) else {}
    if not space and isinstance(message.get("space"), dict):
        space = message["space"]

    merged: dict[str, Any] = dict(body)
    merged["eventType"] = "MESSAGE"
    merged["type"] = "MESSAGE"
    merged["message"] = message
    merged["user"] = user
    merged["space"] = space
    thread = message.get("thread")
    if isinstance(thread, dict):
        merged["thread"] = thread
    return merged


def _message_from_chat_event(event: dict[str, Any]) -> dict[str, Any] | None:
    msg = event.get("message")
    if isinstance(msg, dict):
        return msg
    chat = event.get("chat")
    if not isinstance(chat, dict):
        return None
    mp = chat.get("messagePayload")
    if not isinstance(mp, dict):
        return None
    nested = mp.get("message")
    return nested if isinstance(nested, dict) else None


def extract_user_text_from_chat_event(event: dict[str, Any]) -> str | None:
    """
    Best-effort extraction of what the user typed for a MESSAGE-style Chat event.
    Supports legacy `type`, API `eventType`, and HTTP `chat.messagePayload.message`.
    """
    kind = event.get("eventType") or event.get("type")
    if kind != "MESSAGE":
        return None
    msg = _message_from_chat_event(event)
    if not msg:
        return None
    # argumentText: plain text with @app mentions stripped; for slash commands, args only.
    raw = (
        msg.get("argumentText")
        or msg.get("text")
        or msg.get("formattedText")
        or ""
    )
    if not isinstance(raw, str):
        return None
    text = strip_chat_mentions(raw).strip()
    return text or None


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

    chat_text = extract_user_text_from_chat_event(_normalize_google_chat_http_event(body))
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
