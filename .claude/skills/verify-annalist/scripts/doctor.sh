#!/usr/bin/env bash
# Read-only check: is this verification instance worth driving?
# Usage: doctor.sh [RUN_DIR]   (default runs/verify-annalist/latest)
# Exit 0 when every check passes, 1 otherwise. Changes nothing.
set -uo pipefail
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$SKILL/../../.." && pwd)"
R="$(cd "${1:-$ROOT/runs/verify-annalist/latest}" 2>/dev/null && pwd)" || { echo "FAIL no run dir: ${1:-runs/verify-annalist/latest}"; exit 1; }
[[ -f "$R/state.env" ]] || { echo "FAIL $R/state.env missing: run launch.sh"; exit 1; }
# shellcheck disable=SC1091
. "$R/state.env"
[[ -n "${CLEANED:-}" ]] && { echo "FAIL $R was cleaned up at $CLEANED; evidence is in $EVIDENCE. Run launch.sh for a new instance."; exit 1; }
bad=0
ok() { echo "ok   $*"; }
fail() { echo "FAIL $*"; bad=1; }

[[ -f "$RUN/site/data/wiki.json" ]] && ok "site built: $RUN/site" || fail "no $RUN/site/data/wiki.json (build failed? see $EVIDENCE/build.log)"

if [[ -n "${PID:-}" ]]; then
  cmd="$(tr '\0' ' ' </proc/"$PID"/cmdline 2>/dev/null || true)"
  [[ "$cmd" == *http.server*"$RUN/site"*"$PORT"* ]] && ok "server pid $PID is ours: $cmd" || fail "pid $PID is not our http.server (got: '${cmd:-dead}')"
  owner="$(ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o "pid=[0-9]*" | head -1)"
  [[ "$owner" == "pid=$PID" ]] && ok "port $PORT owned by pid $PID" || fail "port $PORT owner is '${owner:-nobody}', expected pid=$PID"
  python3 - "$BASE" <<'EOF' && ok "wiki.json served: The Salt Ledger, 5 chapters" || fail "wiki.json at $BASE is not the mini book"
import json, sys, urllib.request
w = json.load(urllib.request.urlopen(sys.argv[1] + "data/wiki.json", timeout=5))
sys.exit(0 if w["book"]["max"] == 5 and w["entities"] else 1)
EOF
else
  echo "info no server (launched with --no-serve)"
fi

if cmp -s "$RUN/site/app.js" "$ROOT/annalist/site/app.js" && cmp -s "$RUN/site/app.css" "$ROOT/annalist/site/app.css" && cmp -s "$RUN/site/index.html" "$ROOT/annalist/site/index.html"; then
  ok "served site files match annalist/site/"
else
  fail "served site files differ from annalist/site/: re-export (see SKILL.md Gotchas) or relaunch"
fi
now="$(git -C "$ROOT" rev-parse --short HEAD)$(git -C "$ROOT" diff --quiet -- annalist || echo -dirty)"
[[ "$now" == "$BUILD_SHA" ]] && ok "built from $BUILD_SHA (current)" || echo "warn built from $BUILD_SHA, checkout is now $now: pipeline output may be stale, relaunch to rebuild"

if [[ -f "$RUN/calls.jsonl" ]]; then
  python3 - "$RUN/calls.jsonl" <<'EOF' && ok "every LLM call used the fake backend" || fail "calls.jsonl has non-fake calls or cost"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
sys.exit(0 if all(r.get("backend") == "fake" and not r.get("cost") for r in rows) else 1)
EOF
fi
free_gb="$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)"
[[ "$free_gb" -ge 8 ]] && ok "${free_gb} GB memory available" || fail "only ${free_gb} GB available; the repo rule wants 8 GB before heavy work"
exit $bad
