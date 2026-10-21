"""Creates a Windows Desktop Shortcut for Antigravity Chat Sync.
Run with: python install_desktop_shortcut.py
"""

import os
import subprocess
import sys
from pathlib import Path


def get_real_desktop_path() -> Path:
    """Find the real Desktop directory even if redirected by OneDrive."""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True,
            text=True,
            check=True,
        )
        p = Path(res.stdout.strip())
        if p.exists():
            return p
    except Exception:
        pass

    candidates = [
        Path(os.path.expanduser("~")) / "OneDrive" / "Desktop",
        Path(os.path.expanduser("~")) / "Desktop",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path(os.path.expanduser("~")) / "Desktop"


def create_desktop_shortcut():
    desktop = get_real_desktop_path()
    if not desktop.exists():
        desktop.mkdir(parents=True, exist_ok=True)

    script_dir = Path(__file__).parent.resolve()
    target_bat = script_dir / "AntigravityChatSync.bat"
    shortcut_path = desktop / "Antigravity Chat Sync.lnk"

    # PowerShell command to create shortcut
    ps_cmd = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
    $Shortcut.TargetPath = '{target_bat}'
    $Shortcut.WorkingDirectory = '{script_dir}'
    $Shortcut.Description = 'Sync conversations from Antigravity IDE to Antigravity 2.0'
    $Shortcut.Save()
    """

    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
        print(f"Created shortcut on Desktop: {shortcut_path}")
        return True
    except Exception as e:
        print(f"Failed to create shortcut: {e}")
        return False


if __name__ == "__main__":
    create_desktop_shortcut()
