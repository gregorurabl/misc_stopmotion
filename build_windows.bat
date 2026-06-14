@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

pip install -q -r requirements.txt
pip install -q -r build_requirements.txt

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "OnionFilm" ^
    --add-data "capture;capture" ^
    stopmotion.py

echo Build complete: dist\OnionFilm.exe
