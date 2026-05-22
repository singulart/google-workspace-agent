"""Post replies to Google Chat using the Chat API (app auth via WIF from SSM)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import google.auth.aws
from googleapiclient.discovery import build

from chat_format import format_text_for_google_chat

logger = logging.getLogger(__name__)

CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
_IMDSV2_TOKEN_URL = "http://169.254.169.254/latest/api/token"

_ssm_client: Any | None = None
_chat_service: Any | None = None


def _get_ssm_client() -> Any:
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def _load_wif_config() -> dict[str, Any]:
    parameter_name = os.environ.get("GCP_WIF_CREDENTIAL_CONFIG_SSM_PARAMETER", "").strip()
    if not parameter_name:
        raise RuntimeError("GCP_WIF_CREDENTIAL_CONFIG_SSM_PARAMETER is not set")

    response = _get_ssm_client().get_parameter(Name=parameter_name, WithDecryption=True)
    value = response.get("Parameter", {}).get("Value")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"SSM parameter {parameter_name} is empty")

    config = json.loads(value)
    if not isinstance(config, dict) or config.get("type") != "external_account":
        raise RuntimeError("SSM parameter must contain a WIF external_account JSON object")
    return config


def _normalize_wif_config(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure IMDSv2 token URL is set (required on IMDSv2-only hosts such as AgentCore)."""
    out = dict(config)
    source = out.get("credential_source")
    if isinstance(source, dict):
        merged = dict(source)
        merged.setdefault("imdsv2_session_token_url", _IMDSV2_TOKEN_URL)
        out["credential_source"] = merged
    return out


def _chat_credentials(wif_config: dict[str, Any]) -> google.auth.aws.Credentials:
    """Exchange the runtime AWS role for a Google token (WIF) and impersonate the SA."""
    return google.auth.aws.Credentials.from_info(
        _normalize_wif_config(wif_config),
        scopes=[CHAT_BOT_SCOPE],
    )


def _reset_chat_service() -> None:
    global _chat_service
    _chat_service = None


def _get_chat_service() -> Any:
    global _chat_service
    if _chat_service is None:
        creds = _chat_credentials(_load_wif_config())
        _chat_service = build("chat", "v1", credentials=creds, cache_discovery=False)
    return _chat_service


def post_chat_message(delivery: dict[str, Any], text: str) -> dict[str, Any]:
    """
    Create a message in the space from ``delivery`` (``_delivery`` on the invoke payload).

    Uses app authentication (chat.bot) with credentials from GCP_WIF_CREDENTIAL_CONFIG_SSM_PARAMETER.
    """
    space_name = delivery.get("space_name")
    if not isinstance(space_name, str) or not space_name.strip():
        raise ValueError("delivery.space_name is required")

    body: dict[str, Any] = {"text": format_text_for_google_chat(text).strip()}
    thread_name = delivery.get("thread_name")
    if isinstance(thread_name, str) and thread_name.strip():
        body["thread"] = {"name": thread_name.strip()}

    create_kwargs: dict[str, Any] = {
        "parent": space_name.strip(),
        "body": body,
    }
    request_id = delivery.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        create_kwargs["requestId"] = request_id.strip()

    service = _get_chat_service()
    return (
        service.spaces()
        .messages()
        .create(**create_kwargs)
        .execute()
    )


def try_post_chat_message(delivery: dict[str, Any] | None, text: str) -> bool:
    """Post to Chat when delivery context is present; log and return False on failure."""
    if not delivery:
        return False
    if not text.strip():
        return False
    try:
        result = post_chat_message(delivery, text)
        logger.info(
            "posted chat message name=%s space=%s",
            result.get("name"),
            delivery.get("space_name"),
        )
        return True
    except Exception:
        _reset_chat_service()
        logger.exception(
            "Chat API spaces.messages.create failed space=%s",
            delivery.get("space_name"),
        )
        return False
