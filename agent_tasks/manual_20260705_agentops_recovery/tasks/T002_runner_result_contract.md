# T002 — Runner result contract
- Version: V3.0.1
- Priority: P0
- Owner: hermes_auto_developer
- Status: pending

## Context
Dashboard shows V3.0.1 as partial with agent_ok=False and test_ok=True. Tests pass, but the orchestrator does not reliably recognize the runner result.

## Work
1. Inspect the runner result path from CLI output to completion file.
2. Replace fragile string matching with a stable result signal.
3. Prefer a machine-readable status field in completion JSON or a stable status marker.
4. Keep all existing human approval and safety gates unchanged.
5. Add or update tests for success, partial, blocked, and failed states.

## Acceptance
- A real completed runner result is detected as success by the orchestrator.
- Partial or failed results are not treated as success.
- Relevant pytest tests pass.
- No trading or broker behavior is changed.
