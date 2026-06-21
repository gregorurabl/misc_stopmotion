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

mkdir -p capture

# Generate plist files locally — avoids corruption from browser downloads
cat > entitlements.mac.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.device.camera</key>
    <true/>
</dict>
</plist>
PLIST

cat > info.mac.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>NSCameraUsageDescription</key>
    <string>Onion Film uses the camera for stop-motion frame capture.</string>
    <key>CFBundleName</key>
    <string>OnionFilm</string>
    <key>CFBundleDisplayName</key>
    <string>Onion Film</string>
    <key>CFBundleIdentifier</key>
    <string>at.onionfilm.app</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
</dict>
</plist>
PLIST

# Prefer an older, stable Python — opencv-python has no prebuilt wheels
# for very new versions (e.g. 3.14), which forces a source build that
# fails on older macOS/Xcode toolchains.
PYTHON_BIN=$(command -v python3.11 || command -v python3.12 || command -v python3.10 || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: Python 3.10, 3.11 or 3.12 required."
    echo "Download from https://www.python.org/downloads/macos/"
    exit 1
fi
echo "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate

pip install -q -r requirements.txt
pip install -q -r build_requirements.txt

rm -rf build dist OnionFilm.spec

# --onedir instead of --onefile: onefile + windowed .app re-extracts the
# entire payload on every launch, which is extremely slow on older hardware.
pyinstaller \
    --noconfirm \
    --onedir \
    --windowed \
    --name "OnionFilm" \
    --collect-data customtkinter \
    --add-data "capture:capture" \
    --add-binary "ffmpeg_arm64:." \
    --add-binary "ffmpeg_intel:." \
    stopmotion.py

cp info.mac.plist dist/OnionFilm.app/Contents/Info.plist

codesign --deep --force --sign - \
    --entitlements entitlements.mac.plist \
    dist/OnionFilm.app

echo "Build complete: dist/OnionFilm.app"
echo "Built for architecture: $ARCH"
echo "Launch by double-clicking dist/OnionFilm.app in Finder (not the file inside Contents/MacOS)."
