# Onion Film BETA

Stop-motion capture tool with onion skinning, project management, and ProRes export.

<img width="1126" height="765" alt="grafik" src="https://github.com/user-attachments/assets/86430a1c-bd8e-42e7-a07f-5745db2b9313" />

---

## Requirements

- Python 3.10 or newer
- `tkinter` (part of the standard library; on Linux may need separate installation)
- `ffmpeg` in system PATH (required for video export only)

### Install tkinter (Linux)

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Arch Linux
sudo pacman -S tk

# Fedora
sudo dnf install python3-tkinter
```

### Install ffmpeg

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# macOS (Homebrew)
brew install ffmpeg

# Windows
# Download installer or zip from https://ffmpeg.org/download.html
# Place ffmpeg.exe in a folder on your PATH (e.g. C:\ffmpeg\bin)
```

---

## Installation

### With virtualenv (recommended)

```bash
# Navigate to the project folder
cd /path/to/project

# Create virtual environment
python3 -m venv .venv

# Activate
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows (cmd)
.venv\Scripts\Activate.ps1       # Windows (PowerShell)

# Install dependencies
pip install -r requirements.txt
```

### Without virtualenv (system-wide)

```bash
pip install -r requirements.txt --break-system-packages   # Linux
pip install -r requirements.txt                           # Windows / macOS
```

---

## Running

```bash
# With activated venv
python stopmotion.py

# Without venv (Linux / macOS)
python3 stopmotion.py

# Without venv (Windows)
python stopmotion.py
```

### Launch script (Linux / macOS)

```bash
#!/bin/bash
source "$(dirname "$0")/.venv/bin/activate"
python3 "$(dirname "$0")/stopmotion.py"
```

```bash
chmod +x start.sh
./start.sh
```

---

## Interface

### Camera

| Control | Description |
|---|---|
| **Cam** | OpenCV device index. 0 = first camera, 1 = second, etc. Use `+` / `−` to switch. |
| Name field | Shows the active camera's device name. On Linux the real device name is read from sysfs. For freshly connected USB cameras the name appears after a few seconds. |
| **Save Dir** | Destination folder for PNG frames. Defaults to `capture/` inside the program folder. |

### Capture

- **Capture \[Space\]** — saves the current live frame as a PNG (`frame_0000.png`, `frame_0001.png`, …) into the configured Save Dir folder.
- After each capture the program automatically returns to Live mode.
- Saved PNGs are lossless and can be used independently of the application.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Capture |
| `←` | Step one frame back (Scrub mode) |
| `→` | Step one frame forward (Scrub mode) |

### Modes

| Mode | Description |
|---|---|
| **Live** | Live camera feed with onion skin overlay. Active when the Live button text is green. |
| **Scrub** | Timeline slider or arrow keys display saved frames. Onion skinning is active in this mode too. |
| **Play** | Automatic playback of all saved frames at the configured FPS. |

Clicking **Live** returns to the live feed at any time.

### Timeline

- The slider shows the current position within the saved footage.
- The frame counter on the left shows `current position / total frames`.
- Dragging the slider automatically activates Scrub mode and pauses the live feed.

### Onion Skinning

Onion skinning composites previously captured frames as ghost images over the current view — in Live mode, Scrub mode, and Playback.

| Control | Description |
|---|---|
| **Onion** (checkbox) | Enable / disable onion skinning |
| **Opacity slider** | Opacity of the nearest ghost layer (0.0 – 1.0) |
| **Layer count** (spinbox) | How many previous frames to show as ghost images (0 – 20). Each additional layer receives 0.6× the opacity of the previous one. |

In Live mode the last N saved frames are composited behind the camera feed.  
In Scrub / Play mode the N frames preceding the currently displayed frame are used as ghost layers.

### FPS

Controls playback speed in Play mode and the framerate used during ProRes export. Range: 1 – 60 fps.

---

## Project Management

Onion Film uses a simple JSON project format. PNG frames always remain in the Save Dir folder; the project file stores only the path and settings.

| Button | Action |
|---|---|
| **New Project** | Creates a new numbered subdirectory under `capture/` (`project_001/`, `project_002/`, …) and clears the current frame list. Requires confirmation if frames are already present. |
| **Open Project** | Opens a `.json` project file and loads all associated PNGs from the stored Save Dir path. |
| **Save** | Overwrites the last saved project file. On first save of a new project, Save As is called automatically. |
| **Save As** | Saves under a new name and path. The filename without extension becomes the project name. |

The title bar shows `•` after the project name while there are unsaved changes.

---

## Video Export (ProRes 422HQ)

Requires `ffmpeg` in PATH.

1. Click **Export Video**.
2. Choose a destination path and filename for the `.mov` file.
3. The export runs in the background. The progress bar in the Export row shows completion percentage.
4. The status bar shows `exported: filename.mov` on completion.

Export parameters:
- Codec: `prores_ks`, profile 3 (422 HQ)
- Pixel format: `yuv422p10le` (10-bit)
- Frame rate: the currently configured FPS value
- Resolution: native resolution of the saved PNGs

No bitrate input is required — `prores_ks` derives it internally from resolution and frame rate according to the Apple specification.

---

## Directory Structure

```
stopmotion.py
requirements.txt
README.md
capture/
    project_001/
        frame_0000.png
        frame_0001.png
        …
        project_001.json
    project_002/
        …
```

---

## Known Limitations

- **Linux, camera name:** On systems without full sysfs support the OpenCV backend string (e.g. `V4L2`) is shown instead of the device name.
- **Windows / macOS, camera name:** sysfs resolution is not available; the OpenCV backend string is always shown.
- **ProRes on Windows:** `prores_ks` is included in standard ffmpeg Windows builds. If errors occur, ensure a full build is used rather than `ffmpeg-essentials`.
- **Export progress bar:** The bar is driven by `frame=N` output from ffmpeg stderr. For very short projects (fewer than 5 frames) the bar may jump directly to "done" without intermediate steps.

# License

This project is licensed under the **Free License – No Resale**  
© 2026 [Gregor Urabl, BA](https://gregorurabl.at)

# Summary
- Free to use, copy, and share — even in **commercial projects**  
- **Resale or direct monetization** of the scripts themselves is **not allowed**  
- **Attribution appreciated** but **not required**

See the full [LICENSE.md](./LICENSE.md) for details.
