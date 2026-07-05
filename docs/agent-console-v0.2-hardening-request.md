# Agent Console v0.2 Hardening Request

## Background

Agent Console v0.1 has been implemented and committed as:

`4279c81 feat: add Agent Console with answer_delta SSE streaming`

A follow-up review found that the direction is correct, but v0.1 is not yet enough for product acceptance. This document defines the next hardening tasks.

Work only in this repository:

`/home/ly/.hermes/research-assistant`

Do not use or modify `~/Repo/quant-trading-agent`.

## Main objective

Make Agent Console usable as a real front-end answer interface for Hermes Agent and Claude Code, not just a proof of concept.

The front-end main panel must show user-facing answer text. Runtime details must stay in a secondary diagnostics panel.

## Issue 1 — Claude Code is not token streaming yet

### Current state

The Claude adapter uses Claude Code `--print` mode. This mode may buffer the full response before returning. As a result, the UI may only receive answer chunks after Claude Code completes, not while it is thinking/generating.

### Required work

1. Keep the current `--print` adapter as a stable fallback.
2. Add an explicit capability flag to the Claude adapter, for example:
   - `streaming_mode = buffered`
   - `supports_realtime_delta = false`
3. Show this limitation in the Agent Console UI when Claude Code is selected.
4. Add a v0.2 experimental path for more real-time output:
   - Prefer PTY-based execution if available.
   - Otherwise document why true token streaming is not available from current CLI mode.
5. Do not falsely label buffered chunks as true token streaming.

### Acceptance criteria

- The UI clearly tells the user whether Claude output is buffered or real-time.
- Current Claude Code flow still works.
- There is a documented path to PTY or another streaming-capable Claude invocation.
- Tests cover the capability metadata returned for the Claude adapter.

## Issue 2 — Hermes Agent adapter is not a real research-agent conversation yet

### Current state

The Hermes adapter currently wraps `leader:dispatch --dry-run`. This is useful for validating plumbing, but it is not a true Hermes research conversation or full research-agent answer.

### Required work

1. Keep the current dry-run adapter only as a fallback or demo mode.
2. Add a real Hermes Agent adapter path that can call an actual Hermes research or analysis command and stream the answer into `answer_delta`.
3. Candidate integration points may include:
   - daily research pipeline
   - stock analysis skill
   - sector or semiconductor research skill
   - factor/alpha analysis skill
   - another existing Hermes research command that returns user-facing analysis text
4. Separate modes explicitly:
   - `hermes_demo`
   - `hermes_research`
   - `claude_code`
5. The front-end selector should make clear which mode is selected.
6. Do not present `leader:dispatch --dry-run` as a real research-agent answer.

### Acceptance criteria

- Hermes demo mode remains available for smoke tests.
- At least one real Hermes research command is wired into Agent Console as `answer_delta` output.
- The answer panel shows research-facing text, not dispatch metadata.
- Diagnostics remain secondary.
- Tests verify the mode labels and event separation.

## Issue 3 — Working tree is still not clean

### Current state

Review found the repository still had uncommitted or untracked files, including some combination of:

- `commands/factor_lab/leader/agent_runner.py`
- `commands/factor_lab/leader/dashboard.py`
- `commands/tests/test_leader_dashboard.py`
- `docs/frontend-agent-console-implementation-request.md`
- `docs/hermes-detailed-version-roadmap-v3-v9.md`

Some of these are legitimate follow-up changes, while others may be temporary handoff documents. The tree must not remain ambiguous.

### Required work

1. Inspect `git status --short` and `git diff`.
2. Classify every dirty file as one of:
   - needed product code
   - needed test
   - needed documentation/spec
   - temporary artifact to remove
   - previous experimental patch that should be reverted
3. Keep and commit only coherent changes.
4. Create small commits with clear messages. Suggested commits:
   - `fix: support Agent Console POST session endpoints`
   - `docs: add Agent Console hardening plan`
   - `docs: add detailed Hermes version roadmap`
5. If `agent_runner.py` contains an unrelated streaming-runner patch, either:
   - commit it separately with tests, or
   - revert it if Agent Console no longer depends on it.
6. End with a clean or explicitly explained working tree.

### Acceptance criteria

- `git status --short` is clean, or the final report explains every remaining file.
- POST session creation and cancel endpoints are covered by tests.
- Agent Console tests pass.
- Broader pytest is run after clearing stale lock/task pollution, or the report clearly explains why a runtime-state test failed.

## Required implementation checks

Before reporting completion, verify:

1. `/console` loads.
2. Browser POST create-session works.
3. Browser POST cancel-session works.
4. SSE stream emits events consumable by the front end.
5. The main answer panel renders only `answer_delta`.
6. Diagnostic messages render only in the diagnostics panel.
7. `answer.md` is written for the session.
8. `events.jsonl` is written for the session.
9. Claude Code mode is clearly marked as buffered unless true streaming is implemented.
10. Hermes real research mode is clearly distinguished from demo/dry-run mode.

## Final report format

When done, report:

1. Files changed.
2. Commits created.
3. Agent Console modes available.
4. Whether Claude output is true streaming or buffered.
5. Which Hermes research command is wired as the real Hermes Agent mode.
6. How to start the dashboard.
7. How to open the console.
8. Test commands and results.
9. Final git status.
