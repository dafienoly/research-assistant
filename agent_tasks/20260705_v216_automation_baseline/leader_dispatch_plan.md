# Leader Dispatch Plan — V2.16 Automation Baseline Hardening

## Why this version first

V2.15.2 has made the workloop possible, but before starting V2.17 real data or V3.1 Alpha Discovery, the automation runtime must be hardened:

- ad-hoc verification left an unsafe blocked completion;
- users need one status command instead of reading many JSON files;
- scheduled entrypoints must be stable;
- completed versions need a formal gate before GitHub sync.

## Tasks

- T001: Clear ad-hoc verification state
- T002: Runner status dashboard
- T003: Scheduler entrypoints
- T004: Version completion gate

## Completion contract

When all tasks pass, Hermes must write:

```json
{
  "source": "hermes",
  "version": "V2.16",
  "stage": "automation_baseline_hardening",
  "status": "completed",
  "completed_tasks": ["T001", "T002", "T003", "T004"],
  "remaining_tasks": [],
  "next_question": "Proceed to V2.17 Real Data Contract & No-Fallback Data Hub"
}
```

Then run GitHub sync:

```bash
../.venv_quant/bin/python3 hermes_cli.py leader:github-sync --version V2.16 --summary "automation baseline hardening"
```
