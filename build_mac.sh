#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    FFMPEG="ffmpeg_arm64"
else
    FFMPEG="ffmpeg_intel"
fi

if [ ! -f "$FFMPEG" ]; then
    echo "ERROR: $FFMPEG not found in project root."
    exit 1
fi
chmod +x "$FFMPEG"

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
    --collect-data customtkinter \
    --add-data "capture:capture" \
    --add-binary "ffmpeg_arm64:." \
    --add-binary "ffmpeg_intel:." \
    --info-plist info.mac.plist \
    stopmotion.py

codesign --deep --force --sign - \
    --entitlements entitlements.mac.plist \
    dist/OnionFilm.app

echo "Build complete: dist/OnionFilm.app"
