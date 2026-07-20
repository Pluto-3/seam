#!/bin/bash
# Viewer smoke test - formalizes the manual "start serve, dump the DOM via
# headless Chrome, eyeball it" verification this project has relied on for
# every viewer change so far, into a repeatable, scriptable check.
#
# Deliberately structural, not value-specific: checks that panels are
# populated with *real* data (not the placeholder "-"), not specific numbers
# or accumulated trends. Two things learned the hard way while building this
# (Viewer Wave 3, 2026-07-20) shaped that choice:
#   1. A single live snapshot's fields (tick, population, specialization, the
#      map, societies/leads/settlement) are reliably present moments after
#      the WebSocket connects - safe to assert on.
#   2. Anything that depends on *multiple* WS messages accumulating first
#      (the population/activity sparklines' rolling history) is NOT reliably
#      testable this way - headless Chrome's --virtual-time-budget does not
#      correspond 1:1 to real wall-clock time for a page driven by real
#      network events rather than JS timers, so how many snapshots arrive
#      before the dump fires is not deterministic. That accumulation logic
#      was verified separately, directly, in Node (see LOG.md) - this script
#      does not attempt to re-test it.
#
# Usage: bash core-rs/viewer/smoke_test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_RS_DIR="$(dirname "$SCRIPT_DIR")"
PORT=8199
SERVE_PID=""
FAILURES=0

cleanup() {
  if [ -n "$SERVE_PID" ] && kill -0 "$SERVE_PID" 2>/dev/null; then
    kill -9 "$SERVE_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1"
  FAILURES=$((FAILURES + 1))
}

pass() {
  echo "ok: $1"
}

cd "$CORE_RS_DIR"

echo "building serve (no-op if already up to date)..."
cargo build --bin serve 2>&1 | tail -5

echo "starting serve on port $PORT..."
./target/debug/serve --port "$PORT" --societies 2 --agents 16 --nodes 8 --seed 3 > /tmp/seam_smoke_test_serve.log 2>&1 &
SERVE_PID=$!

echo "waiting for serve to be ready..."
READY=0
for _ in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/leads" 2>/dev/null | grep -q "200"; then
    READY=1
    break
  fi
  sleep 0.5
done
if [ "$READY" -ne 1 ]; then
  fail "serve never became ready on port $PORT - see /tmp/seam_smoke_test_serve.log"
  exit 1
fi

DOM_FILE="/tmp/seam_smoke_test_dom.html"
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=3000 --dump-dom "http://localhost:$PORT/" 2>/dev/null > "$DOM_FILE"

if [ ! -s "$DOM_FILE" ]; then
  fail "headless Chrome produced no DOM output at all"
  exit 1
fi

check_contains() {
  local description="$1"
  local pattern="$2"
  if grep -q "$pattern" "$DOM_FILE"; then
    pass "$description"
  else
    fail "$description (pattern not found: $pattern)"
  fi
}

check_not_contains() {
  local description="$1"
  local pattern="$2"
  if grep -q "$pattern" "$DOM_FILE"; then
    fail "$description (found placeholder/error pattern: $pattern)"
  else
    pass "$description"
  fi
}

check_contains "WebSocket connected"                 'id="status">connected'
check_not_contains "tick shows a real value"          'id="tick">–<'
check_not_contains "population shows a real value"    'id="population">–<'
check_not_contains "specialization shows a real value" 'id="specIdx">–<'
check_not_contains "order power shows a real value"    'id="orderStrength">–<'
# Patterns below deliberately require a real interpolated value (a digit, a
# known seed-deterministic id, a literal LEAD_GOALS string from agents.rs),
# not just the class name or tag - caught for real while building this
# script: class="panel society-card"/lead-card and even <circle all also
# appear verbatim in this file's own <script> source (unevaluated template
# literals like `<circle cx="${p.x...}"`), which --dump-dom includes as page
# text regardless of whether anything actually rendered. A pattern that
# matches the source text as readily as real output isn't testing anything.
check_contains "map has at least one node circle"    '<circle cx="[0-9]'
check_contains "societies panel is populated"        "onclick=\"possessSociety('society0')\""
check_contains "leads panel is populated"            'wealthiest trader in the region'
check_contains "settlement panel is populated"       '<dt>population</dt><dd>[0-9]'

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "SMOKE TEST PASSED"
  exit 0
else
  echo "SMOKE TEST FAILED ($FAILURES check(s) failed) - dumped DOM kept at $DOM_FILE"
  exit 1
fi
