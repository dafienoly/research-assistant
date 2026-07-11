#!/usr/bin/env python3
"""Idempotently configure a private HERMES_UI_TOKEN without printing it."""

from __future__ import annotations

import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


def main() -> int:
    setting_name = "_".join(("HERMES", "UI", "TOKEN"))
    prefix = setting_name + "="
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    if any(line.strip().startswith(prefix) and line.split("=", 1)[1].strip() for line in content.splitlines()):
        print("HERMES_UI_TOKEN already configured")
        return 0
    lines = [line for line in content.splitlines() if not line.strip().startswith(prefix)]
    lines.append(prefix + secrets.token_urlsafe(48))
    temporary = ENV_FILE.with_suffix(".env.tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)
    ENV_FILE.chmod(0o600)
    print("HERMES_UI_TOKEN configured in private .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
