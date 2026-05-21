"""
API Gateway proxy integration: Google Chat event -> AgentCore InvokeAgentRuntime.

The HTTP response is always 200 with an empty JSON object. The agent runtime posts
the user-visible reply via the Chat API (spaces.messages.create) using _delivery
on the invoke payload.
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

from chat_payload import build_chat_delivery

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_PROXY_BODY_LOG_MAX = 4096

_AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
_RUNTIME_ENDPOINT_QUALIFIER = os.environ.get("AGENT_RUNTIME_ENDPOINT_QUALIFIER", "").strip()
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_client = boto3.client("bedrock-agentcore", region_name=_AWS_REGION)

_SESSION_SAFE_RE = re.compile(r"[^a-zA-Z0-9._:-]+")
_RUNTIME_SESSION_ID_MIN_LEN = 33
_RUNTIME_SESSION_ID_MAX_LEN = 256

_ACK_RESPONSE: dict[str, Any] = {
    "statusCode": 200,
    "headers": {"Content-Type": "application/json"},
    "body": "{}",
}


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

    AgentCore / agent/chat_payload expect the legacy Apps Script-style event:
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


def _space_name_from_chat_event(chat_event: dict[str, Any]) -> str:
    space = chat_event.get("space")
    if not isinstance(space, dict) and isinstance(chat_event.get("message"), dict):
        space = chat_event["message"].get("space")
    if isinstance(space, dict):
        name = space.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "unknown-space"


def _runtime_session_id(chat_event: dict[str, Any]) -> str:
    """
    Bedrock AgentCore `runtimeSessionId` scopes conversation state per Chat space.

    Uses only `space.name` (room-wide memory). InvokeAgentRuntime requires 33–256
    characters; shorter values are right-padded with '-'.
    """
    raw = _space_name_from_chat_event(chat_event)
    safe = _SESSION_SAFE_RE.sub("-", raw)[:_RUNTIME_SESSION_ID_MAX_LEN]
    if len(safe) < _RUNTIME_SESSION_ID_MIN_LEN:
        safe = safe.ljust(_RUNTIME_SESSION_ID_MIN_LEN, "-")
    return safe or str(uuid.uuid4())


def _envelope_payload(
    chat_event: dict[str, Any],
    messaging_identity: dict[str, Any] | None,
    delivery: dict[str, Any] | None,
) -> bytes:
    body: dict[str, Any] = dict(chat_event)
    if messaging_identity:
        body["_messaging"] = messaging_identity
    if delivery:
        body["_delivery"] = delivery
    return json.dumps(body).encode("utf-8")


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

    request_context = event.get("requestContext") or {}
    apigw_request_id = request_context.get("requestId")
    request_id = apigw_request_id if isinstance(apigw_request_id, str) else None

    delivery = build_chat_delivery(parsed, request_id=request_id)
    if delivery:
        logger.info("delivery space=%s thread=%s", delivery.get("space_name"), delivery.get("thread_name"))

    messaging_identity = _parse_messaging_identity(event)
    payload_bytes = _envelope_payload(chat_event, messaging_identity, delivery)
    session_id = _runtime_session_id(chat_event)

    invoke_kwargs: dict[str, Any] = {
        "agentRuntimeArn": _AGENT_RUNTIME_ARN,
        "runtimeSessionId": session_id,
        "payload": payload_bytes,
        "contentType": "application/json",
        "accept": "application/json",
    }
    if _RUNTIME_ENDPOINT_QUALIFIER:
        invoke_kwargs["qualifier"] = _RUNTIME_ENDPOINT_QUALIFIER

    try:
        _client.invoke_agent_runtime(**invoke_kwargs)
    except Exception as exc:
        logger.exception("InvokeAgentRuntime failed: %s", exc)

    return dict(_ACK_RESPONSE)
