"""Launcher script for Antigravity Chat Sync CLI.
Run with: python run_cli.py [command]
"""

import os
import sys

package_root = os.path.dirname(os.path.abspath(__file__))
if package_root not in sys.path:
    sys.path.insert(0, package_root)

from antigravity_chat_sync.cli import main

if __name__ == "__main__":
    main()
