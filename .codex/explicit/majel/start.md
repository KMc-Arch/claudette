---
version: 1
short-desc: Dispatch a directive to Majel; reply surfaces async via background subagent
isolation: inline
reads: []
writes: []
---

# majel

Dispatch a directive to Majel — the knowledge-base MCP server at `/mnt/claudette/majel/`. Majel's pipeline can take 1–3 minutes per request. Rather than block the main session on polling, `/majel` delegates the ask/check loop to a background subagent.

The caller is **dispatching a directive**, not conversing. One shot in, one shot back. Clarification is a second dispatch, not a multi-turn chat.

## Usage

`/majel <content>` — dispatch the content verbatim to Majel.

Empty content is an error — refuse and prompt the user for a directive.

## Execution

1. **Parse.** Everything after `/majel` is the directive content, passed to Majel verbatim. Do not rewrite, reinterpret, or prepend an intent verb — Majel's own pipeline handles intent parsing.

2. **Announce dispatch immediately.** Before spawning the subagent, tell the user:

   `Dispatched to Majel. Reply will surface when ready.`

   This makes fire-and-forget visible. The user continues the conversation while Majel works.

3. **Spawn one background subagent** via the Agent tool with:
   - `subagent_type: general-purpose`
   - `run_in_background: true`
   - A self-contained prompt (see template below).

4. **On subagent completion**, surface Majel's reply using the format below. If the subagent returns a `continues` token, trigger the clarification loop.

## Subagent prompt template

The subagent inherits MCP tool access. Brief it to handle the full ask/check loop without further main-session involvement:

> You are dispatching a directive to Majel and returning her reply. Do not interpret or respond on her behalf — your job is to relay.
>
> **Steps:**
> 1. Call `mcp__majel__ask` with `content: "<DIRECTIVE>"`{, `continues: "<TOKEN>"` if this is a clarification round-trip}. Capture `request_id`.
> 2. Poll `mcp__majel__check(request_id)` every 20 seconds.
> 3. Loop until `status` is `answered`, `abandoned`, or `unknown`.
>    - On `answered`: return Majel's `reply` text and the `continues` token (if any).
>    - On `abandoned`: return `STATUS: abandoned` — Majel dropped the request, user should retry.
>    - On `unknown`: return `STATUS: unknown` — bad request_id, something went wrong.
> 4. Do not exceed **15 minutes** total wait time. If the loop has not resolved by then, return `STATUS: timeout (request_id=<id>)`.
>
> **Return format** (structured for the main session to parse):
> ```
> REPLY:
> <Majel's reply text verbatim>
>
> CONTINUES: <token or "none">
> STATUS: <final status>
> ```

Fill `<DIRECTIVE>` with the exact content the user passed. Fill `<TOKEN>` only when running a clarification round-trip.

## Surfacing the reply

When the subagent completes, present Majel's reply with minimal ceremony. Terse dispatch — no quoting frame, no commentary, no `@majel` persona. Prefix with `Majel:` and then the verbatim reply text.

**Example:**
```
Majel: Noted. The cascade-direction rule is now held as an always-loaded decisions entry.
```

On non-`answered` statuses, surface the status line as-is:
- `Majel: STATUS abandoned — dispatch again to retry.`
- `Majel: STATUS unknown — request_id invalid.`
- `Majel: STATUS timeout — still pending after 15m. Check again later with the original request_id.`

## Clarification loop

If the subagent returns a non-null `CONTINUES` token alongside the reply:

1. Surface Majel's clarifying question to the user using the standard reply format.
2. Wait for the user's next message.
3. Treat that message as the answer. Spawn a **fresh** background subagent with the user's answer as `<DIRECTIVE>` and the captured token as `<TOKEN>`.
4. Surface the next reply the same way. Continue until `CONTINUES` is `none`.

Each round-trip is one full subagent delegation. Do not try to anticipate or answer Majel's clarifications on the user's behalf.
