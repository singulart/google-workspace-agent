# Two-phase Gmail reads (Vincent + MCP)

Vincent’s system prompt (`agent/vincent_agent.py`) instructs a **discover → triage → hydrate** flow aligned with the gmail-dwd-mcp-server read tools.

## Architecture

| Phase | Tool | What you get |
|-------|------|----------------|
| Discover | `search_threads` | Thread IDs (`messages: []`) from one `threads.list` |
| Hydrate | `get_threads` / `get_thread` | Normalized plain text in each message `body` |

Write tools (`create_draft`, labels, etc.) are unchanged.

## Manual test scenario (F1 checklist)

Prerequisites: runtime has `GMAIL_MCP_GATEWAY_URL` set; gateway exposes `search_threads`, `get_threads`, and `get_thread`.

1. **Search** — Ask Vincent: “List unread threads from the last day” (or similar).
   - [ ] Agent calls `search_threads` with a reasonable query.
   - [ ] Response to user does not quote full email bodies (only ids / high-level summary).

2. **Hydrate** — Follow up: “Read the two most relevant threads in full.”
   - [ ] Agent calls `get_threads` (or two `get_thread` calls) with explicit thread IDs from step 1.
   - [ ] Answer cites content from hydrated `body` fields.

3. **Truncation** — If possible, hydrate a long thread with many messages.
   - [ ] When `meta.truncated` or `omittedFromThread` applies, agent mentions incomplete content.

4. **Direct IDs** — User message: “Summarize thread `<known-id>`.”
   - [ ] Agent skips `search_threads` and calls `get_thread` or `get_threads` directly.

5. **Batch size** — Ask for many threads at once (>10).
   - [ ] Agent splits into multiple `get_threads` calls or explains the limit, rather than one huge batch.

## Prompt review checklist (manual)

- [ ] `_SYSTEM_PROMPT` mentions `search_threads` and `get_threads`
- [ ] Prompt states search does not return message bodies
- [ ] Prompt requires hydrate step before citing email content
- [ ] Prompt mentions `meta.truncated` / omissions
- [ ] Prompt warns about small batches and session memory
