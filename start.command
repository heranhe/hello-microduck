#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
if [ ! -x backend/.venv/bin/python ]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/python -m pip install -r backend/requirements.txt
exec backend/.venv/bin/python backend/server.py
