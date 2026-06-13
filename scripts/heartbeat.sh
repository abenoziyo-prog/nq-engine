#!/usr/bin/env bash
# minimal liveness ping; replace echo with a curl to your notify webhook
echo "[$(date -Is)] nq-engine host alive" >> "$(dirname "$0")/../logs/heartbeat.log"
