#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${ROOT_DIR}/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "${ROOT_DIR}/pyproject.toml" || ! -f "${ROOT_DIR}/ytrec_probe/cli.py" ]]; then
  echo "error: package files are missing under ${ROOT_DIR}" >&2
  exit 1
fi

if [[ -d "${VENV_DIR}" ]]; then
  echo "Removing existing virtual environment: ${VENV_DIR}"
  rm -rf -- "${VENV_DIR}"
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install --force-reinstall "${ROOT_DIR}"

"${VENV_DIR}/bin/python" - <<'PY'
import ytrec_probe
import ytrec_probe.cli
print(f"Installed ytrec-probe {ytrec_probe.__version__}")
print(f"Package: {ytrec_probe.__file__}")
print(f"CLI:     {ytrec_probe.cli.__file__}")
PY


echo
echo "Installation completed."
echo "Run: ${ROOT_DIR}/run.sh collect 'https://www.youtube.com/@CHANNEL_HANDLE'"
