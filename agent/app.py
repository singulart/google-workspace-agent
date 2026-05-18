"""
Bedrock AgentCore HTTP agent: GET /ping, POST /invocations.

Google Chat calls a public HTTPS URL directly; Agent Core uses /invocations with
SigV4 on the AWS side. For Chat, either:
  - point Chat at a small public bridge that calls InvokeAgentRuntime and maps
    `response` -> Chat `{"text": ...}`, or
  - run this image behind that public URL and set CHAT_DIRECT_MODE=1 so POST /
    returns Google Chat synchronous message JSON (see handlers for fields).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from handlers import format_google_chat_sync_reply, process_invocation_body
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

_CHAT_DIRECT = os.environ.get("CHAT_DIRECT_MODE", "").lower() in ("1", "true", "yes")


async def ping(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "Healthy",
            "time_of_last_update": int(time.time()),
        }
    )


async def invocations(request: Request) -> JSONResponse:
    raw = await request.body()
    print(raw.decode("utf-8", errors="replace"), flush=True)
    try:
        body: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return JSONResponse(
            {"response": "Expected application/json body.", "status": "error"},
            status_code=400,
        )

    result = process_invocation_body(body)
    print(result, flush=True)
    return JSONResponse(result)


async def chat_http_root(request: Request) -> JSONResponse:
    """Optional Google Chat HTTP endpoint (same JSON as Chat sends to /)."""
    raw = await request.body()
    print(raw.decode("utf-8", errors="replace"), flush=True)
    try:
        body: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return JSONResponse({}, status_code=400)

    result = process_invocation_body(body)
    text = (result.get("response") or "").strip()
    return JSONResponse(format_google_chat_sync_reply(text, body))


routes = [
    Route("/ping", endpoint=ping, methods=["GET"]),
    Route("/invocations", endpoint=invocations, methods=["POST"]),
]

if _CHAT_DIRECT:
    routes.append(Route("/", endpoint=chat_http_root, methods=["POST"]))

app = Starlette(debug=False, routes=routes)
