#!/usr/bin/env python3
"""Local runner for Hermes research checks."""

import subprocess
from pathlib import Path

ROOT = Path('/home/ly/.hermes/research-assistant/commands')
PY = Path('/home/ly/.hermes/research-assistant/.venv_quant/bin/python3')


def run(cmd):
    print('+', ' '.join(str(x) for x in cmd))
    subprocess.run([str(x) for x in cmd], cwd=str(ROOT), check=True)


if __name__ == '__main__':
    run([PY, 'hermes_cli.py', 'leader:inspect'])
    run([PY, 'hermes_cli.py', 'leader:accept', '--full-tests'])
