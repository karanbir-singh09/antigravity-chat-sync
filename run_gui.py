"""Launcher script for Antigravity Chat Sync GUI.
Run with: python run_gui.py
"""

import os
import sys

# Ensure package root is in sys.path
package_root = os.path.dirname(os.path.abspath(__file__))
if package_root not in sys.path:
    sys.path.insert(0, package_root)

from antigravity_chat_sync.gui.app import AntigravityChatSyncApp


def main():
    app = AntigravityChatSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
