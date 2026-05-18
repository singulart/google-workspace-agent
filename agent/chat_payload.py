"""Parse Google Chat and AgentCore invocation payloads (no HTTP framework)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MENTION_RE = re.compile(r"<users/[^>]+>")


@dataclass(frozen=True)
class InvocationInput:
    """Normalized user turn for the Strands agent."""

    user_message: str
    actor_id: str
    source: str


def strip_chat_mentions(text: str) -> str:
    t = _MENTION_RE.sub("", text)
    return " ".join(t.split())


def _normalize_google_chat_http_event(body: dict[str, Any]) -> dict[str, Any]:
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
    kind = event.get("eventType") or event.get("type")
    if kind != "MESSAGE":
        return None
    msg = _message_from_chat_event(event)
    if not msg:
        return None
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


def actor_id_from_payload(body: dict[str, Any]) -> str:
    messaging = body.get("_messaging")
    if isinstance(messaging, dict):
        subject = messaging.get("subject")
        if isinstance(subject, str) and subject.strip():
            return subject.strip()

    event = _normalize_google_chat_http_event(body)
    user = event.get("user")
    if isinstance(user, dict):
        for key in ("name", "email", "displayName"):
            value = user.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    space = event.get("space")
    if isinstance(space, dict):
        name = space.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    return "anonymous"


def extract_invocation_input(body: dict[str, Any]) -> InvocationInput | None:
    """
  Return a user turn to send to the Strands agent, or None if the event should be ignored.
  """
    prompt = body.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return InvocationInput(
            user_message=prompt.strip(),
            actor_id=actor_id_from_payload(body),
            source="prompt",
        )

    chat_text = extract_user_text_from_chat_event(_normalize_google_chat_http_event(body))
    if chat_text is not None:
        return InvocationInput(
            user_message=chat_text,
            actor_id=actor_id_from_payload(body),
            source="google_chat_message",
        )

    kind = body.get("eventType") or body.get("type")
    if kind:
        return None

    return InvocationInput(
        user_message='Send {"prompt": "Hello"} or a Google Chat MESSAGE event.',
        actor_id=actor_id_from_payload(body),
        source="unknown_payload",
    )
