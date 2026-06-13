#!/usr/bin/env bash
# build_digest.sh — summarize today's build progress to the operator.
set -euo pipefail
cd "$(dirname "$0")/.."
claude -p "Read build/state/STATUS.json and the last 24h of build/state/BUILDLOG.md. Send the operator a <=150-word digest: tasks completed today, tasks blocked (and why), current phase progress (X of 23 done), and any decisions needed. Then stop." \
  --output-format text --permission-mode acceptEdits 2>&1 | tee -a logs/digest.log
