#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-${ROOT_DIR}/venv}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/experiment/live-output}"
SEEDS="${SEEDS:-3}"
RECOMMENDATIONS="${RECOMMENDATIONS:-10}"

rm -rf -- "${OUTPUT_DIR}"
"${ROOT_DIR}/run.sh" collect \
  'https://www.youtube.com/@sugishun_tech' \
  --seeds "${SEEDS}" \
  --recommendations "${RECOMMENDATIONS}" \
  --delay 0 \
  --output-dir "${OUTPUT_DIR}"

"${VENV_DIR}/bin/python" - "${OUTPUT_DIR}/channels.csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding="utf-8-sig", newline="") as fp:
    rows = list(csv.DictReader(fp))

if not rows:
    raise SystemExit("live test failed: channels.csv has no data rows")
missing = [row["channel_name"] for row in rows if not row.get("channel_url", "").strip()]
if missing:
    preview = ", ".join(missing[:10])
    raise SystemExit(
        f"live test failed: {len(missing)} channel_url value(s) are empty: {preview}"
    )
print(f"live test passed: {len(rows)} channel rows, all channel_url values populated")
PY
