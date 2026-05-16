"""
API Gateway TOKEN authorizer for Google Chat HTTPS requests.

Validates the Bearer token Google sends (project-number JWT or HTTP-endpoint OIDC).
On success, returns a stable messaging_identity in authorizer context (not the raw JWT).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CHAT_CERTS_URL = (
    "https://www.googleapis.com/service_accounts/v1/metadata/x509/" + CHAT_ISSUER
)
# HTTP-endpoint audience tokens can be classic Chat OIDC (email=CHAT_ISSUER) or
# Google ID tokens (iss=https://accounts.google.com, e.g. gcp-sa-gsuiteaddons SA).
_GOOGLE_ACCOUNTS_ISS = frozenset({"https://accounts.google.com", "accounts.google.com"})

_AUTH_MODE = os.environ.get("GOOGLE_CHAT_AUTH_MODE", "project_number").strip().lower()
_AUDIENCE = os.environ.get("GOOGLE_CHAT_AUDIENCE", "").strip()

_BEARER_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


def _deny(message: str) -> None:
    logger.error("Unauthorized: %s", message)
    raise Exception("Unauthorized")


def _extract_bearer(authorization_token: str) -> str:
    if not authorization_token:
        _deny("missing Authorization")
    match = _BEARER_RE.match(authorization_token.strip())
    if match:
        return match.group(1).strip()
    return authorization_token.strip()


def _verify_project_number_jwt(token: str, audience: str) -> dict[str, Any]:
    request = google_requests.Request()
    claims = id_token.verify_token(
        token,
        request,
        audience=audience,
        certs_url=CHAT_CERTS_URL,
    )
    if claims.get("iss") != CHAT_ISSUER:
        _deny("invalid issuer")
    return claims


def _verify_http_url_oidc(token: str, audience: str) -> dict[str, Any]:
    """
    Audience must match the Chat app HTTPS URL exactly (including trailing slash).

    Google may send either:
    - Legacy: email == chat@system.gserviceaccount.com (per older Chat samples), or
    - Current: iss https://accounts.google.com and a Workspace add-ons style SA email.
    """
    request = google_requests.Request()
    claims = id_token.verify_oauth2_token(token, request, audience)
    if not claims.get("email_verified"):
        _deny("email not verified")

    email = claims.get("email") or ""
    iss = claims.get("iss") or ""

    if email == CHAT_ISSUER:
        return claims

    if iss in _GOOGLE_ACCOUNTS_ISS:
        # Google-signed ID token for this audience; principal is Google's SA for the app.
        if not email.endswith(".gserviceaccount.com"):
            _deny("unexpected principal type")
        return claims

    _deny("token not from Google Chat / Workspace for this endpoint")


def _messaging_identity(claims: dict[str, Any]) -> dict[str, Any]:
    return {
        "channel": "google_chat",
        "auth_mode": _AUTH_MODE,
        "issuer": claims.get("iss") or CHAT_ISSUER,
        "audience": _AUDIENCE,
        "subject": claims.get("sub") or claims.get("email") or CHAT_ISSUER,
    }


def _event_for_log(event: dict[str, Any]) -> dict[str, Any]:
    """Log shape API Gateway passes; never log the raw JWT."""
    out = dict(event)
    tok = out.get("authorizationToken")
    if isinstance(tok, str) and tok:
        out["authorizationToken"] = f"<redacted len={len(tok)}>"
    elif "authorizationToken" in out:
        out["authorizationToken"] = "<empty>"
    return out


def _allow_policy(method_arn: str) -> dict[str, Any]:
    # method_arn: arn:aws:execute-api:region:account:apiId/stage/METHOD/resource
    parts = method_arn.split(":")
    api_gw_arn_tail = ":".join(parts[5:]).split("/")
    api_id = api_gw_arn_tail[0]
    stage = api_gw_arn_tail[1] if len(api_gw_arn_tail) > 1 else "*"
    region = parts[3]
    account = parts[4]
    resource = f"arn:aws:execute-api:{region}:{account}:{api_id}/{stage}/*/*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "execute-api:Invoke",
                "Effect": "Allow",
                "Resource": resource,
            }
        ],
    }


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    logger.info("authorizer event: %s", json.dumps(_event_for_log(event)))

    if not _AUDIENCE:
        _deny("GOOGLE_CHAT_AUDIENCE not configured")

    token = _extract_bearer(event.get("authorizationToken") or "")
    try:
        if _AUTH_MODE == "http_url":
            claims = _verify_http_url_oidc(token, _AUDIENCE)
        else:
            claims = _verify_project_number_jwt(token, _AUDIENCE)
    except Exception:
        _deny("token verification failed")

    identity = _messaging_identity(claims)
    return {
        "principalId": identity["subject"],
        "policyDocument": _allow_policy(event["methodArn"]),
        "context": {
            "messaging_identity": json.dumps(identity, separators=(",", ":")),
        },
    }
