#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

pip install -q -r requirements.txt
pip install -q -r build_requirements.txt

pyinstaller \
    --noconfirm \
    --onefile \
    --windowed \
    --name "OnionFilm" \
    --add-data "capture:capture" \
    stopmotion.py

echo "Build complete: dist/OnionFilm"
