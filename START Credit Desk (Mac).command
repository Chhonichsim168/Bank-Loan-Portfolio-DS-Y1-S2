#!/bin/bash
# Credit Desk - double-click to start on a Mac (also works on Linux: bash "START Credit Desk (Mac).command").
cd "$(dirname "$0")" || exit 1
echo "================================================================"
echo "  CREDIT DESK"
echo "================================================================"

# ----------------------------------------------------------------------------------
# OPTIONAL SWITCHES (remove "# " at the start of a line to turn it on)
# Open with NO sign-in page at all:
# export CREDIT_DESK_REQUIRE_LOGIN=0
# Start WITHOUT the sample loans and decisions (set this BEFORE the very first start):
# export CREDIT_DESK_SAMPLE_DATA=0
# ----------------------------------------------------------------------------------

if [ ! -f app.py ]; then
  echo "The app files were not found next to this file. Extract the whole project folder first."
  read -r -p "Press Enter to close"; exit 1
fi

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed. The download page will open now."
  echo "Install Python, then double-click this file again."
  open "https://www.python.org/downloads/" 2>/dev/null || xdg-open "https://www.python.org/downloads/" 2>/dev/null
  read -r -p "Press Enter to close"; exit 1
fi

"$PY" launch.py
read -r -p "Press Enter to close"
