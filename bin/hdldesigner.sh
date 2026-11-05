#!/usr/bin/env bash
# =============================================================================================
# Start HDLDesigner (Design Manager) on Linux. Arguments are passed on, e.g.
#     bin/hdldesigner.sh /path/to/project.hdp
# Uses the virtual environment .venv of the repository when there is one, else python3.
# =============================================================================================
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$ROOT/bin/hdldesigner.py" "$@"
