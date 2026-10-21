@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw run_gui.py
) else (
    python run_gui.py
)
