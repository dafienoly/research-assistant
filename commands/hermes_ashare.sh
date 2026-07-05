#!/usr/bin/env bash
# Hermes A股投研助手 — Bash 命令入口
# 添加到 PATH 或 alias hermes-ashare=/path/to/hermes_ashare.sh

set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/hermes_cli.py" "$@"
