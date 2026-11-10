#!/usr/bin/env bash
# Build the five-chapter test book with the fake backend and serve its site.
# Usage: launch.sh [RUN_ID] [--epub PATH] [--no-serve]
# Prints the run directory. State goes to runs/verify-annalist/<RUN_ID>/state.env.
set -euo pipefail
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$SKILL/../../.." && pwd)"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
if [[ $# -gt 0 && "$1" != --* ]]; then RUN_ID="$1"; shift; fi
EPUB="$ROOT/tests/data/mini.epub"
SERVE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --epub) EPUB="$2"; shift 2 ;;
    --no-serve) SERVE=0; shift ;;
    *) echo "unknown arg $1" >&2; exit 64 ;;
  esac
done

R="$ROOT/runs/verify-annalist/$RUN_ID"
WORK="$R/work"
EVIDENCE="$R/evidence"
mkdir -p "$WORK" "$EVIDENCE"
ln -sfn "$RUN_ID" "$ROOT/runs/verify-annalist/latest"

python3 "$SKILL/scripts/seed.py" "$WORK" >/dev/null
# Clean env: no ANNALIST_* overrides, stub claude first on PATH.
CLEAN_ENV=(env)
for v in $(compgen -e | grep '^ANNALIST_' || true); do CLEAN_ENV+=(-u "$v"); done
CLEAN_ENV+=(PATH="$WORK/bin:$PATH")
cd "$ROOT"
"${CLEAN_ENV[@]}" python3 -m annalist build "$EPUB" "$WORK/run" --yes >"$EVIDENCE/build.log" 2>&1 \
  || { echo "build failed, see $EVIDENCE/build.log" >&2; tail -20 "$EVIDENCE/build.log" >&2; exit 2; }

{
  echo "RUN_ID=$RUN_ID"
  echo "ROOT=$ROOT"
  echo "R=$R"
  echo "WORK=$WORK"
  echo "RUN=$WORK/run"
  echo "EVIDENCE=$EVIDENCE"
  echo "BUILD_SHA=$(git -C "$ROOT" rev-parse --short HEAD)$(git -C "$ROOT" diff --quiet -- annalist || echo -dirty)"
} >"$R/state.env"

if [[ "$SERVE" == 1 ]]; then
  PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
  nohup python3 -m http.server --bind 127.0.0.1 -d "$WORK/run/site" "$PORT" >"$WORK/server.log" 2>&1 &
  PID=$!
  {
    echo "PORT=$PORT"
    echo "PID=$PID"
    echo "BASE=http://127.0.0.1:$PORT/"
  } >>"$R/state.env"
  for _ in $(seq 50); do
    curl -sf "http://127.0.0.1:$PORT/data/wiki.json" -o /dev/null && break
    sleep 0.1
  done
  curl -sf "http://127.0.0.1:$PORT/data/wiki.json" -o /dev/null || { echo "server not answering on $PORT" >&2; exit 3; }
fi
echo "$R"
