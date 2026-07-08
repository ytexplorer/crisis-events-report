#!/bin/bash
# SessionStart hook for crisis-events-report.
#
# Runs once the repo is already checked out in the working directory (this
# hook cannot bootstrap the clone itself — see README/routine.md for the
# environment-level Source configuration that provides the initial clone
# on a fresh environment). Installs the one Python dependency (Jinja2) so
# `python3 feeds_store.py render` works immediately.
set -euo pipefail

cd "$CLAUDE_PROJECT_DIR"
pip install -q -r requirements.txt
