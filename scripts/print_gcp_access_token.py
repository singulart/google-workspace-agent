#!/usr/bin/env python3
"""
Fetch a Google access token on AWS (e.g. EC2) using Workload Identity Federation.

Prerequisites on the instance:
  - This repo's WIF JSON on disk (e.g. clientLibraryConfig-argorand.json).
  - An instance profile with an IAM role (so IMDS can return AWS credentials).
  - Environment (optional; defaults to ./clientLibraryConfig-argorand.json next to CWD):
      export GOOGLE_APPLICATION_CREDENTIALS=/path/to/wif.json

  If your instance requires IMDSv2 only, the JSON from the console may need the
  imdsv2 fields — regenerate with:
    gcloud iam workload-identity-pools create-cred-config ... --aws --enable-imdsv2
"""

from __future__ import annotations

import argparse
import os
import sys

import google.auth
import google.auth.transport.requests

# Default scope for a generic “can I get a token?” test; adjust for Gmail later.
_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "cred_path",
        nargs="?",
        default=None,
        help="Path to WIF JSON. If omitted, uses GOOGLE_APPLICATION_CREDENTIALS.",
    )
    args = parser.parse_args()
    if args.cred_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(args.cred_path)
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        # sensible default for this repo layout
        here = os.path.dirname(os.path.abspath(__file__))
        default_json = os.path.join(here, "..", "clientLibraryConfig-argorand.json")
        if os.path.isfile(default_json):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(default_json)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path or not os.path.isfile(path):
        print(
            "Set GOOGLE_APPLICATION_CREDENTIALS to your WIF JSON path "
            "or pass it as the first argument.",
            file=sys.stderr,
        )
        return 1

    credentials, _project = google.auth.default(scopes=list(_DEFAULT_SCOPES))
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)

    token = credentials.token
    if not token:
        print("No access token after refresh — check IMDS, pool bindings, and scopes.", file=sys.stderr)
        return 1

    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
