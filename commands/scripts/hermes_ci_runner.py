#!/usr/bin/env python3
"""Local runner for Hermes research checks."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import VENV_PYTHON

ROOT = Path(VENV_PYTHON).resolve().parent.parent.parent / "commands"
PY = Path(VENV_PYTHON)


def run(cmd):
    print('+', ' '.join(str(x) for x in cmd))
    subprocess.run([str(x) for x in cmd], cwd=str(ROOT), check=True)


if __name__ == '__main__':
    run([PY, 'hermes_cli.py', 'leader:inspect'])
    run([PY, 'hermes_cli.py', 'leader:accept', '--full-tests'])
