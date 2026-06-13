#!/usr/bin/env bash
# run_routine.sh — invokes Claude Code headless on a prompt file, logs output.
# Usage: ./run_routine.sh P1_eod.txt
set -euo pipefail
cd "$(dirname "$0")/.."                      # repo root
PROMPT_FILE="routines/prompts/$1"
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/routine_${1%.txt}_$TS.log"
mkdir -p logs

# headless Claude Code run; reads CLAUDE.md from repo root automatically.
# ANTHROPIC_API_KEY must be set in the environment (see .env / systemd unit).
claude -p "$(cat "$PROMPT_FILE")" \
  --output-format text \
  --permission-mode acceptEdits \
  >> "$LOG" 2>&1

echo "[$TS] $1 complete -> $LOG"
