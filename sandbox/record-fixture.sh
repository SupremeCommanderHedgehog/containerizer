#!/usr/bin/env bash
# Regenerate tests/fixtures/trace/synthetic-recorded/ from a real
# `containerizer trace` run against the synthetic installer. Not
# wired into CI — run by hand whenever the collector schema changes
# enough that the committed fixture goes stale.
#
# Usage (Linux/podman host):
#   bash sandbox/record-fixture.sh
#
# After this finishes, also re-run:
#   containerizer analyze tests/fixtures/trace/synthetic-recorded \
#       -o tests/fixtures/analyze/expected
#   mv tests/fixtures/analyze/expected/trace.json tests/fixtures/analyze/expected/synthetic-trace.json
#   mv tests/fixtures/analyze/expected/policy.json tests/fixtures/analyze/expected/synthetic-policy.json
# to refresh the goldens, then commit both.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TRACE_OUT=$(mktemp -d)
RECORDED="$ROOT/tests/fixtures/trace/synthetic-recorded"

containerizer trace "$ROOT/tests/fixtures/trace/synthetic-installer.sh" -o "$TRACE_OUT"

# Scrub ts_ns + phase_marker_ns to monotonic-relative starting at 0
# so the fixture is bit-stable across recordings.
python3 - "$TRACE_OUT" "$RECORDED" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)

# Find baseline ts_ns
baseline = None
for p in sorted(src.glob("*.jsonl")):
    for line in p.read_text().splitlines():
        if line.startswith("{"):
            r = json.loads(line)
            if isinstance(r.get("ts_ns"), int):
                baseline = min(baseline, r["ts_ns"]) if baseline is not None else r["ts_ns"]

if baseline is None:
    baseline = 0

def rewrite(line):
    if not line.startswith("{"):
        return line
    r = json.loads(line)
    if isinstance(r.get("ts_ns"), int):
        r["ts_ns"] -= baseline
    if isinstance(r.get("first_ts_ns"), int):
        r["first_ts_ns"] -= baseline
    return json.dumps(r)

for p in sorted(src.iterdir()):
    if p.name in ("COMPLETE", "PARTIAL", "FALLBACKS.json"):
        (dst / p.name).write_bytes(p.read_bytes())
    elif p.name == "PHASE_MARKER":
        text = p.read_text().strip()
        if text.startswith("monotonic_ns:"):
            ns = int(text.split(":", 1)[1].strip())
            (dst / p.name).write_text(f"monotonic_ns: {ns - baseline}\n")
        else:
            (dst / p.name).write_bytes(p.read_bytes())
    elif p.suffix == ".jsonl":
        lines = [rewrite(line) for line in p.read_text().splitlines()]
        (dst / p.name).write_text("\n".join(lines) + ("\n" if lines else ""))
PY
echo "wrote $RECORDED"
rm -rf "$TRACE_OUT"
