#!/usr/bin/env bash
# run_build.sh — fires one build-agent task via headless Claude Code.
set -euo pipefail
cd "$(dirname "$0")/.."
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/build_$TS.log"
mkdir -p logs
# headless Claude Code; reads CLAUDE.md + the manifest automatically from the repo.
# --permission-mode acceptEdits lets it write files & commit; it cannot place trades (no creds wired to a live path).
claude -p "$(cat build/BUILD_AGENT_PROMPT.txt)" \
  --output-format text \
  --permission-mode acceptEdits \
  >> "$LOG" 2>&1
echo "[$TS] build run complete -> $LOG"
