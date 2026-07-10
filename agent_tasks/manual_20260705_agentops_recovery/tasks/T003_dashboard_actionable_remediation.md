# T003 — Dashboard actionable remediation panel
- Version: V3.0.1
- Priority: P1
- Owner: hermes_auto_developer
- Status: pending

## Context
The Dashboard can now show status, roadmap details, and SSE logs. The next improvement is to make red/yellow states actionable. The user wants to see not only what failed, but also why it failed and what command or manual step should be used next.

## Work
1. Add a remediation section to the Dashboard status model.
2. For each detected state issue, generate an explanation and a recommended next action.
3. Cover at least these cases:
   - dirty git tree
   - stale latest task versus cursor version
   - partial completion
   - missing report_dir
   - coding backend not configured
   - runner log contains traceback or import error
   - old polluted task markers in current task files
4. Render the remediation section in the local Dashboard HTML.
5. Keep the page read-only. Do not add buttons that run commands yet.

## Acceptance
- /api/status contains a remediation or next_actions field.
- The Dashboard renders these suggestions clearly.
- Tests check that the field exists and covers at least dirty git tree and partial completion.
- Existing /api/status, /api/roadmap, and /api/stream behavior still works.
