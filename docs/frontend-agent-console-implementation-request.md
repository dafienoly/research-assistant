# Frontend Agent Console Implementation Request

## Important clarification

This task is not about log tailing. The user wants a web page that shows the real-time answer text produced by Hermes Agent and Claude Code.

Runtime logs, stdout, stderr, file paths, and diagnostics may be displayed in a secondary collapsible panel, but they must not be the primary output.

## Goal

Implement a local Agent Console inside Hermes so the user can:

1. Open a browser page.
2. Choose an engine: Hermes Agent or Claude Code.
3. Enter a prompt/task.
4. Start a session.
5. Watch the agent answer text stream into the main answer panel while the process is running.
6. Cancel the session if needed.

## Required event model

Use separate event types:

- `answer_delta`: user-facing answer text, appended to the main response panel.
- `status`: session state updates such as starting, running, done, canceled, error.
- `diagnostic`: secondary runtime details, shown only in a diagnostics panel.
- `error`: visible error message.

Do not use file-tail logs as the main answer stream.

## Backend requirements

Add a small session service, preferably under `commands/factor_lab/agent_console/` or a similar local-only module.

Suggested APIs:

- `POST /api/agent-console/sessions`
- `GET /api/agent-console/sessions/{session_id}`
- `GET /api/agent-console/sessions/{session_id}/stream`
- `POST /api/agent-console/sessions/{session_id}/cancel`

The stream endpoint should use SSE first. WebSocket can be added later.

Session files should be persisted under:

`agent_tasks/agent_console_sessions/<session_id>/`

Suggested files:

- `request.json`
- `events.jsonl`
- `answer.md`
- `diagnostics.log`
- `summary.json`

## Engine adapter requirements

Create a common adapter interface for Hermes Agent and Claude Code.

Each adapter must yield structured events, especially `answer_delta`.

If the underlying CLI only emits stdout chunks, classify chunks carefully:

- model answer text -> `answer_delta`
- runner metadata -> `diagnostic`
- process lifecycle -> `status`

Claude Code should be launched in a way that exposes its response stream as directly as possible. If `--print` buffers too much, document that limitation and add a PTY-based fallback plan.

## Frontend requirements

Add a page or dashboard section titled `Agent Console`.

Required UI:

- engine selector
- prompt textarea
- start button
- cancel button
- main answer panel
- secondary diagnostics panel
- session status indicator

Main answer panel must subscribe to `answer_delta` events and append visible answer text.

Diagnostics panel may display status, command, stderr, and runtime details, but must be visually secondary.

## Safety and scope

Work only in `/home/ly/.hermes/research-assistant`.
Do not use or modify `~/Repo/quant-trading-agent`.
Keep this console local-only by default, bound to `127.0.0.1`.
Do not add any external execution or brokerage behavior.

## Acceptance tests

Add tests that verify:

1. The session API can create a session.
2. The stream endpoint emits `answer_delta` events.
3. The frontend contains an Agent Console UI.
4. The main answer panel is populated from `answer_delta`, not from log-tail events.
5. Existing dashboard APIs still work.

## Delivery

After implementation, provide:

- changed files
- how to start the server
- how to open the page
- how to test with a sample prompt
- known limitations, especially buffering behavior of the local engine CLI
