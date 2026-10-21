"""Backup management module for Antigravity databases.
Provides automatic snapshots and rollback capabilities.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import SyncConfig, default_config


class BackupManager:
    def __init__(self, config: SyncConfig = default_config):
        self.config = config

    def create_snapshot(self) -> Dict[str, str]:
        """Create timestamped backups of conversation_summaries.db and state.vscdb.
        Returns dict of {target_name: backup_path}.
        """
        now = datetime.now()
        ts = int(now.timestamp())
        created = {}

        # 1. conversation_summaries.db
        db_path = self.config.app_summaries_db_path
        if db_path.exists():
            backup_db = db_path.parent / f"conversation_summaries.db.backup_{ts}"
            try:
                shutil.copy2(db_path, backup_db)
                created["summaries_db"] = str(backup_db)
            except Exception as e:
                pass

        # 2. Antigravity 2.0 state.vscdb
        vscdb_path = self.config.app_vscdb_path
        if vscdb_path.exists():
            backup_vscdb = vscdb_path.parent / f"state.vscdb.backup_{ts}"
            try:
                shutil.copy2(vscdb_path, backup_vscdb)
                created["vscdb"] = str(backup_vscdb)
            except Exception as e:
                pass

        return created

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available database backups."""
        backups: List[Dict[str, Any]] = []
        db_parent = self.config.app_summaries_db_path.parent
        if db_parent.exists():
            for f in db_parent.glob("conversation_summaries.db.backup_*"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    backups.append(
                        {
                            "type": "conversation_summaries.db",
                            "path": str(f),
                            "filename": f.name,
                            "size_bytes": f.stat().st_size,
                            "timestamp": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                            "mtime": f.stat().st_mtime,
                        }
                    )
                except Exception:
                    pass

        # Also state.vscdb backups
        vscdb_parent = self.config.app_vscdb_path.parent
        if vscdb_parent.exists():
            for f in vscdb_parent.glob("state.vscdb.backup_*"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    backups.append(
                        {
                            "type": "state.vscdb",
                            "path": str(f),
                            "filename": f.name,
                            "size_bytes": f.stat().st_size,
                            "timestamp": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                            "mtime": f.stat().st_mtime,
                        }
                    )
                except Exception:
                    pass

        # Sort newest first
        backups.sort(key=lambda b: -b["mtime"])
        return backups

    def restore_backup(self, backup_path_str: str) -> bool:
        """Restore a database from a backup file."""
        backup_path = Path(backup_path_str)
        if not backup_path.exists():
            return False

        if "conversation_summaries.db.backup_" in backup_path.name:
            target = self.config.app_summaries_db_path
            shutil.copy2(backup_path, target)
            return True
        elif "state.vscdb.backup_" in backup_path.name:
            target = self.config.app_vscdb_path
            shutil.copy2(backup_path, target)
            return True

        return False
