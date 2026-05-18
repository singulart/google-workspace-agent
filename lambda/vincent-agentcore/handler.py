"""
API Gateway proxy integration: Google Chat event -> AgentCore InvokeAgentRuntime -> Chat reply.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import uuid
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_PROXY_BODY_LOG_MAX = 4096

_AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
_RUNTIME_ENDPOINT_QUALIFIER = os.environ.get("AGENT_RUNTIME_ENDPOINT_QUALIFIER", "").strip()
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_client = boto3.client("bedrock-agentcore", region_name=_AWS_REGION)

_SESSION_SAFE_RE = re.compile(r"[^a-zA-Z0-9._:-]+")


def _api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _parse_messaging_identity(event: dict[str, Any]) -> dict[str, Any] | None:
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    raw = authorizer.get("messaging_identity")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _raw_apigateway_body_text(event: dict[str, Any]) -> str:
    """API Gateway proxy: body is a string; may be base64-encoded when isBase64Encoded is true."""
    raw = event.get("body")
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return json.dumps(raw)
    if not isinstance(raw, str):
        return ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(raw).decode("utf-8")
    return raw


def _normalize_google_chat_http_event(body: dict[str, Any]) -> dict[str, Any]:
    """
    Workspace Chat HTTP interactions often use a wrapper:
      { "commonEventObject", "authorizationEventObject", "chat": { "user", "messagePayload" } }

    AgentCore / agent/handlers expect the legacy Apps Script-style event:
      { "type"|"eventType": "MESSAGE", "message": {...}, "user", "space", ... }.
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


def _runtime_session_id(chat_event: dict[str, Any]) -> str:
    """
    Bedrock AgentCore `runtimeSessionId` is chosen by the client to scope conversation
    state — it is not assigned by Google. Prefer a Chat thread id when present so
    threaded DMs stay coherent; otherwise space + user.
    """
    thread: dict[str, Any] = {}
    if isinstance(chat_event.get("thread"), dict):
        thread = chat_event["thread"]
    elif isinstance(chat_event.get("message"), dict):
        mt = chat_event["message"].get("thread")
        if isinstance(mt, dict):
            thread = mt
    thread_name = (thread.get("name") or "").strip()
    if thread_name:
        raw = thread_name
    else:
        space = chat_event.get("space") or {}
        user = chat_event.get("user") or {}
        space_name = space.get("name") or "unknown-space"
        user_name = user.get("name") or "unknown-user"
        raw = f"{space_name}:{user_name}"
    safe = _SESSION_SAFE_RE.sub("-", raw)[:256]
    return safe or str(uuid.uuid4())


def _envelope_payload(chat_event: dict[str, Any], messaging_identity: dict[str, Any] | None) -> bytes:
    body: dict[str, Any] = dict(chat_event)
    if messaging_identity:
        body["_messaging"] = messaging_identity
    return json.dumps(body).encode("utf-8")


def _read_agentcore_body(response: dict[str, Any]) -> dict[str, Any]:
    content_type = (response.get("contentType") or "").lower()
    stream = response.get("response")
    if stream is None:
        return {}

    if "text/event-stream" in content_type:
        chunks: list[str] = []
        for line in stream.iter_lines(chunk_size=4096):
            if not line:
                continue
            text = line.decode("utf-8") if isinstance(line, bytes) else str(line)
            if text.startswith("data: "):
                chunks.append(text[6:])
        joined = "\n".join(chunks)
        return json.loads(joined) if joined.strip() else {}

    parts: list[str] = []
    if hasattr(stream, "read"):
        data = stream.read()
        if isinstance(data, bytes):
            parts.append(data.decode("utf-8"))
        else:
            parts.append(str(data))
    else:
        for chunk in stream:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode("utf-8"))
            else:
                parts.append(str(chunk))

    text = "".join(parts).strip()
    if not text:
        return {}
    return json.loads(text)


def _event_for_log(event: dict[str, Any]) -> dict[str, Any]:
    """Compact API Gateway proxy event for CloudWatch (body truncated)."""
    rc = event.get("requestContext") or {}
    identity = rc.get("identity") or {}
    raw = event.get("body")
    if raw is None:
        body: str | bytes = ""
    elif isinstance(raw, bytes):
        body = raw
    else:
        body = str(raw)
    preview: str | None
    if isinstance(body, str):
        preview = (body[:_PROXY_BODY_LOG_MAX] + "…") if len(body) > _PROXY_BODY_LOG_MAX else body
    else:
        preview = f"<bytes len={len(body)}>"
    return {
        "requestId": rc.get("requestId"),
        "httpMethod": event.get("httpMethod"),
        "path": event.get("path"),
        "sourceIp": identity.get("sourceIp"),
        "bodyLength": len(body),
        "bodyPreview": preview,
    }


def _uses_workspace_addon_http_format(body: dict[str, Any]) -> bool:
    if isinstance(body.get("chat"), dict):
        return True
    if isinstance(body.get("commonEventObject"), dict):
        return True
    if isinstance(body.get("authorizationEventObject"), dict):
        return True
    return False


def _to_chat_reply(
    agent_result: dict[str, Any],
    request_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = (agent_result.get("response") or "").strip()
    if not text:
        return {}
    if request_body is not None and _uses_workspace_addon_http_format(request_body):
        # Workspace add-ons HTTP pipeline (chat.messagePayload requests).
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


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        payload = json.dumps(_event_for_log(event), default=str)
    except Exception as exc:
        print(f"proxy event log serialization failed: {exc!r}")
        payload = repr(event)[:_PROXY_BODY_LOG_MAX]
    logger.info("proxy event: %s", payload)

    try:
        text = _raw_apigateway_body_text(event)
    except (UnicodeDecodeError, binascii.Error):
        return _api_response(400, {"error": "Invalid request body encoding"})

    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError:
        return _api_response(400, {"error": "Invalid JSON body"})

    if not isinstance(parsed, dict):
        return _api_response(400, {"error": "Expected JSON object"})

    chat_event = _normalize_google_chat_http_event(parsed)

    messaging_identity = _parse_messaging_identity(event)
    payload = _envelope_payload(chat_event, messaging_identity)
    session_id = _runtime_session_id(chat_event)

    invoke_kwargs: dict[str, Any] = {
        "agentRuntimeArn": _AGENT_RUNTIME_ARN,
        "runtimeSessionId": session_id,
        "payload": payload,
        "contentType": "application/json",
        "accept": "application/json",
    }
    if _RUNTIME_ENDPOINT_QUALIFIER:
        invoke_kwargs["qualifier"] = _RUNTIME_ENDPOINT_QUALIFIER

    try:
        response = _client.invoke_agent_runtime(**invoke_kwargs)
    except Exception as exc:
        print(f"InvokeAgentRuntime failed: {exc!r}")
        return _api_response(502, {"error": "Agent runtime invocation failed"})

    try:
        agent_result = _read_agentcore_body(response)
    except json.JSONDecodeError:
        return _api_response(502, {"error": "Invalid agent runtime response"})

    return _api_response(200, _to_chat_reply(agent_result, parsed))
