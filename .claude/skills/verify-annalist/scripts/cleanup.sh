#!/usr/bin/env bash
# Stop the server this run started and delete its scratch build. Keeps evidence/.
# Usage: cleanup.sh [RUN_DIR]   (default runs/verify-annalist/latest)
set -uo pipefail
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$SKILL/../../.." && pwd)"
R="$(cd "${1:-$ROOT/runs/verify-annalist/latest}" 2>/dev/null && pwd)" || { echo "no run dir"; exit 1; }
[[ -f "$R/state.env" ]] || { echo "$R/state.env missing; nothing to clean"; exit 0; }
# shellcheck disable=SC1091
. "$R/state.env"
case "$R" in "$ROOT"/runs/verify-annalist/*) ;; *) echo "refusing: $R is outside runs/verify-annalist"; exit 1 ;; esac

if [[ -n "${PID:-}" ]]; then
  cmd="$(tr '\0' ' ' </proc/"$PID"/cmdline 2>/dev/null || true)"
  if [[ "$cmd" == *http.server*"$RUN/site"* ]]; then
    kill "$PID" && echo "stopped server pid $PID (port $PORT)"
  elif [[ -n "$cmd" ]]; then
    echo "pid $PID is not our server ($cmd); left it running"
  else
    echo "server pid $PID already gone"
  fi
fi
rm -rf "$WORK" && echo "removed $WORK"
sed -i '/^PID=/d;/^PORT=/d;/^BASE=/d;/^CLEANED=/d' "$R/state.env"
echo "CLEANED=$(date -Iseconds)" >>"$R/state.env"
echo "evidence kept: $EVIDENCE"
ls "$EVIDENCE"
