"""Configuration module for Antigravity Chat Sync.
Handles paths, constants, and environment detection.
"""

import os
import sys
from pathlib import Path

# Base user directory
USER_HOME = Path(os.path.expanduser("~"))
APPDATA_ROAMING = Path(os.environ.get("APPDATA", USER_HOME / "AppData" / "Roaming"))

# Antigravity IDE directories
DEFAULT_IDE_BASE = USER_HOME / ".gemini" / "antigravity-ide"
DEFAULT_IDE_ROAMING = APPDATA_ROAMING / "Antigravity IDE"

# Antigravity 2.0 directories
DEFAULT_APP_BASE = USER_HOME / ".gemini" / "antigravity"
DEFAULT_APP_ROAMING = APPDATA_ROAMING / "Antigravity"

# Shared Gemini configuration directory
DEFAULT_GEMINI_DIR = USER_HOME / ".gemini"
DEFAULT_CONFIG_PROJECTS_DIR = DEFAULT_GEMINI_DIR / "config" / "projects"
DEFAULT_PROJECTS_JSON = DEFAULT_GEMINI_DIR / "projects.json"


class SyncConfig:
    def __init__(
        self,
        ide_base: Path = DEFAULT_IDE_BASE,
        ide_roaming: Path = DEFAULT_IDE_ROAMING,
        app_base: Path = DEFAULT_APP_BASE,
        app_roaming: Path = DEFAULT_APP_ROAMING,
        config_projects_dir: Path = DEFAULT_CONFIG_PROJECTS_DIR,
        projects_json: Path = DEFAULT_PROJECTS_JSON,
    ):
        self.ide_base = Path(ide_base)
        self.ide_roaming = Path(ide_roaming)
        self.app_base = Path(app_base)
        self.app_roaming = Path(app_roaming)
        self.config_projects_dir = Path(config_projects_dir)
        self.projects_json = Path(projects_json)

    @property
    def ide_convs_dir(self) -> Path:
        return self.ide_base / "conversations"

    @property
    def ide_brain_dir(self) -> Path:
        return self.ide_base / "brain"

    @property
    def ide_vscdb_path(self) -> Path:
        return self.ide_roaming / "User" / "globalStorage" / "state.vscdb"

    @property
    def app_convs_dir(self) -> Path:
        return self.app_base / "conversations"

    @property
    def app_brain_dir(self) -> Path:
        return self.app_base / "brain"

    @property
    def app_summaries_db_path(self) -> Path:
        return self.app_base / "conversation_summaries.db"

    @property
    def app_proto_path(self) -> Path:
        return self.app_base / "agyhub_summaries_proto.pb"

    @property
    def app_vscdb_path(self) -> Path:
        return self.app_roaming / "User" / "globalStorage" / "state.vscdb"

    def validate(self) -> dict:
        """Validate path presence and return a status dict."""
        return {
            "ide_base_exists": self.ide_base.exists(),
            "ide_convs_exists": self.ide_convs_dir.exists(),
            "ide_brain_exists": self.ide_brain_dir.exists(),
            "ide_vscdb_exists": self.ide_vscdb_path.exists(),
            "app_base_exists": self.app_base.exists(),
            "app_convs_exists": self.app_convs_dir.exists(),
            "app_brain_exists": self.app_brain_dir.exists(),
            "app_summaries_db_exists": self.app_summaries_db_path.exists(),
            "app_vscdb_exists": self.app_vscdb_path.exists(),
            "projects_json_exists": self.projects_json.exists(),
        }


# Default global instance
default_config = SyncConfig()
