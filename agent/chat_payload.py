"""Parse Google Chat and AgentCore invocation payloads."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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


def default_timezone() -> str:
    """IANA timezone for session clock (matches ``DEFAULT_TIMEZONE`` on the runtime)."""
    tz = os.environ.get("DEFAULT_TIMEZONE", "").strip()
    return tz or "UTC"


def now_iso(*, timezone: str | None = None, now: datetime | None = None) -> tuple[str, str]:
    """
    Current instant as ISO 8601 in the given or default timezone.

    Returns ``(iso_string, timezone_name)``.
    """
    tz_name = timezone or default_timezone()
    zone = ZoneInfo(tz_name)
    instant = now if now is not None else datetime.now(tz=zone)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=zone)
    else:
        instant = instant.astimezone(zone)
    return instant.isoformat(), tz_name


def format_agent_user_message(
    text: str,
    *,
    user_email: str | None = None,
    now: datetime | None = None,
) -> str:
    """
    Wrap the user turn with session context the model should use for date resolution.

    Injects authoritative ``<now_iso>`` and ``<timezone>`` on every turn so Gmail
    ``after:`` / ``before:`` filters do not rely on the model calling ``current_time``.
    """
    now_iso_str, tz_name = now_iso(now=now)
    lines = [
        "<session_context>",
        f"  <now_iso>{now_iso_str}</now_iso>",
        f"  <timezone>{tz_name}</timezone>",
    ]
    if user_email:
        lines.append(f"  <user_email>{user_email}</user_email>")
    lines.extend(
        [
            "</session_context>",
            "",
            "<user_message>",
            text,
            "</user_message>",
            "",
        ]
    )
    return "\n".join(lines)


def _user_email_from_event(event: dict[str, Any]) -> str | None:
    """Workspace email from ``chat.user.email`` or normalized ``event.user.email``."""
    chat = event.get("chat")
    if isinstance(chat, dict):
        user = chat.get("user")
        if isinstance(user, dict):
            email = user.get("email")
            if isinstance(email, str) and email.strip():
                return email.strip()
    user = event.get("user")
    if isinstance(user, dict):
        email = user.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip()
    return None


def _normalize_google_chat_http_event(body: dict[str, Any]) -> dict[str, Any]:
    kind = body.get("eventType") or body.get("type")
    if kind == "MESSAGE" and isinstance(body.get("message"), dict):
        if isinstance(body.get("user"), dict):
            return body
        chat = body.get("chat")
        if isinstance(chat, dict) and isinstance(chat.get("user"), dict):
            merged = dict(body)
            merged["user"] = chat["user"]
            return merged
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
    if not text:
        return None

    email = _user_email_from_event(event)
    if not email:
        return None

    return format_agent_user_message(text, user_email=email)


def _space_name_from_event(event: dict[str, Any]) -> str | None:
    space = event.get("space")
    if not isinstance(space, dict) and isinstance(event.get("message"), dict):
        space = event["message"].get("space")
    if isinstance(space, dict):
        name = space.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def build_chat_delivery(
    body: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Routing context for ``spaces.messages.create``.

    Serialized on the AgentCore invoke payload as ``_delivery`` by the Lambda bridge.
    """
    event = _normalize_google_chat_http_event(body)
    kind = event.get("eventType") or event.get("type")
    if kind != "MESSAGE":
        return None

    space_name = _space_name_from_event(event)
    if not space_name:
        return None

    msg = _message_from_chat_event(event)
    thread_name: str | None = None
    message_name: str | None = None
    if isinstance(msg, dict):
        thread = msg.get("thread")
        if isinstance(thread, dict):
            tn = thread.get("name")
            if isinstance(tn, str) and tn.strip():
                thread_name = tn.strip()
        mn = msg.get("name")
        if isinstance(mn, str) and mn.strip():
            message_name = mn.strip()

    delivery: dict[str, Any] = {"space_name": space_name}
    if thread_name:
        delivery["thread_name"] = thread_name
    if message_name:
        delivery["message_name"] = message_name
    if isinstance(request_id, str) and request_id.strip():
        delivery["request_id"] = request_id.strip()
    return delivery


def delivery_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``_delivery`` from the invoke envelope, or derive it from the Chat event."""
    existing = payload.get("_delivery")
    if isinstance(existing, dict):
        space = existing.get("space_name")
        if isinstance(space, str) and space.strip():
            return existing
    return build_chat_delivery(payload)


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
    actor_id = actor_id_from_payload(body)
    event = _normalize_google_chat_http_event(body)
    user_email = _user_email_from_event(event)

    prompt = body.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return InvocationInput(
            user_message=format_agent_user_message(
                prompt.strip(),
                user_email=user_email,
            ),
            actor_id=actor_id,
            source="prompt",
        )

    chat_text = extract_user_text_from_chat_event(event)
    if chat_text is not None:
        return InvocationInput(
            user_message=chat_text,
            actor_id=actor_id,
            source="google_chat_message",
        )

    kind = body.get("eventType") or body.get("type")
    if kind:
        return None

    return InvocationInput(
        user_message=format_agent_user_message(
            'Send {"prompt": "Hello"} or a Google Chat MESSAGE event.',
            user_email=user_email,
        ),
        actor_id=actor_id,
        source="unknown_payload",
    )
