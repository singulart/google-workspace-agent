#!/usr/bin/env python3
"""
List recent Gmail message IDs for a Workspace user using domain-wide delegation.

Prerequisites
-------------
1. A WIF ADC JSON that includes *service account impersonation* (field
   service_account_impersonation_url). The service
   account must be the one you enabled for domain-wide delegation.
2. In Google Admin: API controls → Domain-wide delegation → the service
   account *client ID* (numeric), with the Gmail scope(s) you use below.
3. Gmail API enabled on the GCP project.
4. On AWS: same as your token test (IMDS, etc.) and IAM binding so your role can
   impersonate that service account (roles/iam.workloadIdentityUser on the SA).

A token from *direct* WIF (no service_account_impersonation_url) is a federated
identity — it is not valid for the Gmail user mailbox API.

Usage
-----
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/wif-with-sa-impersonation.json
  python scripts/gmail_list_messages.py --user user@yourdomain.com
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from typing import Any

import google.auth.aws
import google.auth.impersonated_credentials
import google.auth.transport.requests
from googleapiclient.discovery import build

# Request only what you need. Must match (or be a subset of) what you authorized in Admin.
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
)


def _parse_sa_email_from_impersonation_url(url: str) -> str | None:
    # e.g. .../serviceAccounts/name@project.iam.gserviceaccount.com:generateAccessToken
    m = re.search(r"serviceAccounts/([^:]+)", url)
    return m.group(1) if m else None


def _wif_config_without_sa_impersonation(config: dict[str, Any]) -> dict[str, Any]:
    """Strip SA impersonation so the result is AWS→STS only; used as DWD source."""
    c = copy.deepcopy(config)
    c.pop("service_account_impersonation_url", None)
    c.pop("service_account_impersonation", None)
    return c


def _delegated_credentials(user_email: str, path: str):
    with open(path, encoding="utf-8") as f:
        info: dict[str, Any] = json.load(f)
    if info.get("type") != "external_account":
        print("Expected a WIF external_account JSON.", file=sys.stderr)
        raise SystemExit(1)

    impersonation_url = info.get("service_account_impersonation_url")
    if not impersonation_url:
        print(
            "This file has no service_account_impersonation_url.\n"
            "Regenerate the ADC with your delegated service account (WIF + SA).\n"
            "A *direct* federated token cannot call the Gmail API for a user mailbox.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    sa_email = _parse_sa_email_from_impersonation_url(impersonation_url)
    if not sa_email:
        print("Could not parse service account email from service_account_impersonation_url.", file=sys.stderr)
        raise SystemExit(1)

    wif_info = _wif_config_without_sa_impersonation(info)
    source = google.auth.aws.Credentials.from_info(wif_info)
    source = source.with_scopes(list(GMAIL_SCOPES))

    # Domain-wide delegation: WIF source → act as service account with sub=user.
    return google.auth.impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=sa_email,
        target_scopes=list(GMAIL_SCOPES),
        subject=user_email,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("Prerequisites")[0].strip())
    parser.add_argument(
        "--user",
        required=True,
        help="Workspace mailbox to read (must match a user you delegate to in Admin).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        help="Max messages to list (default: 10).",
    )
    args = parser.parse_args()

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path or not os.path.isfile(path):
        print("Set GOOGLE_APPLICATION_CREDENTIALS to a WIF JSON (with SA impersonation).", file=sys.stderr)
        raise SystemExit(1)

    creds = _delegated_credentials(args.user, path)
    request = google.auth.transport.requests.Request()
    creds.refresh(request)

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    # userId is the mailbox; with DWD, use the same address you passed as subject.
    result = (
        service.users()
        .messages()
        .list(userId=args.user, maxResults=args.max)
        .execute()
    )
    messages = result.get("messages", [])
    if not messages:
        print("No messages in response (inbox may be empty or no access).")
        return 0
    for m in messages:
        msg = (
            service.users()
            .messages()
            .get(
                userId=args.user,
                id=m.get("id"),
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
        )
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in msg.get("payload", {}).get("headers", [])
        }
        print(
            f"id={m.get('id')} "
            f"thread={m.get('threadId')} "
            f"subject={headers.get('subject', '(no subject)')} "
            f"from={headers.get('from', '(unknown sender)')} "
            f"date={headers.get('date', '(no date)')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
