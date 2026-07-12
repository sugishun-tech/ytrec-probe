#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${ROOT_DIR}/venv}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "error: virtual environment not found. Run ${ROOT_DIR}/install.sh first." >&2
  exit 1
fi

exec "${VENV_DIR}/bin/python" -m ytrec_probe "$@"
