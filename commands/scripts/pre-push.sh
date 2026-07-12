#!/bin/sh
# Hermes pre-push hook intentionally disabled.
#
# Code audit is an explicit, release-only action:
#   python commands/hermes_cli.py audit:code --major-version 2.0.0 \
#     --scope compare --base origin/main
#
# Do not scan data/temp trees or block ordinary development pushes here.
exit 0
