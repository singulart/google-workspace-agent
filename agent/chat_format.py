"""Normalize assistant text for Google Chat message markup."""

from __future__ import annotations

import re

# **bold** / __bold__ → *bold* (Chat text messages, not GitHub markdown)
_GITHUB_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_GITHUB_BOLD_UNDERSCORE_RE = re.compile(r"__([^_\n]+?)__")
# ### Heading → *Heading*
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
# [label](url) → <url|label>
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def format_text_for_google_chat(text: str) -> str:
    """Best-effort map of common Markdown to Google Chat text syntax."""
    if not text:
        return text
    text = _GITHUB_BOLD_RE.sub(r"*\1*", text)
    text = _GITHUB_BOLD_UNDERSCORE_RE.sub(r"*\1*", text)
    text = _MARKDOWN_HEADING_RE.sub(r"*\1*", text)
    text = _MARKDOWN_LINK_RE.sub(r"<\2|\1>", text)
    return text
