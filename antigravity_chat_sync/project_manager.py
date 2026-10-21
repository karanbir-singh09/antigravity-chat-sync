"""Project detection, mapping, and automatic registration for Antigravity 2.0.
Ensures every synced workspace appears cleanly in Antigravity 2.0's Project Switcher.
"""

import json
import os
import re
import sqlite3
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import SyncConfig, default_config


class ProjectInfo:
    def __init__(
        self,
        id: str,
        name: str,
        folder_uri: str,
        local_path: str,
        slug: str,
    ):
        self.id = id
        self.name = name
        self.folder_uri = folder_uri
        self.local_path = local_path.lower().rstrip("\\/")
        self.slug = slug

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "folder_uri": self.folder_uri,
            "local_path": self.local_path,
            "slug": self.slug,
        }

    def __repr__(self) -> str:
        return f"<ProjectInfo name={self.name!r} id={self.id[:8]} path={self.local_path}>"


class ProjectManager:
    def __init__(self, config: SyncConfig = default_config):
        self.config = config
        self._projects: Dict[str, ProjectInfo] = {}  # id -> ProjectInfo
        self._path_to_id: Dict[str, str] = {}  # normalized local path -> project_id
        self._uri_to_id: Dict[str, str] = {}  # normalized URI -> project_id
        self.reload()

    @staticmethod
    def normalize_uri(uri: str) -> str:
        if not uri:
            return ""
        uri = uri.strip().rstrip("/\\")
        # Unquote percent-encoding
        unquoted = urllib.parse.unquote(uri).lower().replace("\\", "/")
        return unquoted

    @staticmethod
    def uri_to_local_path(uri: str) -> str:
        if not uri:
            return ""
        # Handle file:///c:/... or file:///c%3A/...
        unquoted = urllib.parse.unquote(uri).replace("\\", "/")
        if unquoted.startswith("file:///"):
            path = unquoted[len("file:///") :]
            # Windows drive letter formatting: c:/... -> C:\...
            if len(path) > 1 and path[1] == ":":
                path = path.replace("/", "\\")
            return path.lower().rstrip("\\")
        return uri.lower().replace("/", "\\").rstrip("\\")

    @staticmethod
    def local_path_to_uri(local_path: str) -> str:
        norm = local_path.replace("\\", "/").rstrip("/")
        # Example format: file:///c%3A/Users/username/project
        if len(norm) > 1 and norm[1] == ":":
            drive = norm[0]
            rest = norm[2:]
            return f"file:///{drive}%3A{rest}"
        return f"file:///{norm}"

    @staticmethod
    def make_slug(name: str) -> str:
        clean = re.sub(r"[^\w\s-]", "", name).strip().lower()
        return re.sub(r"[-\s]+", "-", clean)

    def reload(self) -> None:
        """Load all project configurations from config/projects and projects.json."""
        self._projects.clear()
        self._path_to_id.clear()
        self._uri_to_id.clear()

        # 1. Read config/projects/*.json
        proj_dir = self.config.config_projects_dir
        if proj_dir.exists():
            for f in proj_dir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    pid = data.get("id", f.stem)
                    name = data.get("name", f.stem)
                    resources = data.get("projectResources", {}).get("resources", [])
                    folder_uri = resources[0].get("folderUri", "") if resources else ""
                    local_path = self.uri_to_local_path(folder_uri)
                    slug = self.make_slug(name)

                    info = ProjectInfo(
                        id=pid,
                        name=name,
                        folder_uri=folder_uri,
                        local_path=local_path,
                        slug=slug,
                    )
                    self._projects[pid] = info
                    if local_path:
                        self._path_to_id[local_path] = pid
                    if folder_uri:
                        self._uri_to_id[self.normalize_uri(folder_uri)] = pid
                except Exception:
                    pass

        # 2. Correlate with projects.json
        p_json_path = self.config.projects_json
        if p_json_path.exists():
            try:
                with open(p_json_path, "r", encoding="utf-8") as fp:
                    p_data = json.load(fp)
                for path_str, slug in p_data.get("projects", {}).items():
                    norm_path = path_str.lower().rstrip("\\/")
                    # If already mapped, update slug if needed
                    if norm_path not in self._path_to_id:
                        # find if a project with matching slug exists
                        matched_pid = None
                        for pid, pinfo in self._projects.items():
                            if pinfo.slug == slug:
                                matched_pid = pid
                                break
                        if matched_pid:
                            self._path_to_id[norm_path] = matched_pid
            except Exception:
                pass

    def get_all_projects(self) -> List[ProjectInfo]:
        """Return a list of all loaded projects sorted by name."""
        return sorted(self._projects.values(), key=lambda p: p.name.lower())

    def match_project(self, workspace_uri_or_path: str) -> Optional[ProjectInfo]:
        """Match a workspace URI or file/dir path to an existing registered project."""
        if not workspace_uri_or_path:
            return None

        # Check URI match first
        norm_uri = self.normalize_uri(workspace_uri_or_path)
        if norm_uri in self._uri_to_id:
            return self._projects[self._uri_to_id[norm_uri]]

        # Check local path match
        local_path = self.uri_to_local_path(workspace_uri_or_path)
        if local_path in self._path_to_id:
            return self._projects[self._path_to_id[local_path]]

        # Subdirectory or prefix match
        for path_prefix, pid in self._path_to_id.items():
            if local_path.startswith(path_prefix) or path_prefix.startswith(local_path):
                return self._projects.get(pid)

        # Name-based match from URI segments
        uri_last_part = norm_uri.rstrip("/").split("/")[-1].lower()
        if uri_last_part:
            for pid, pinfo in self._projects.items():
                if pinfo.name.lower() == uri_last_part or pinfo.slug == uri_last_part:
                    return pinfo

        return None

    def ensure_project(
        self,
        workspace_uri_or_path: str,
        display_name: Optional[str] = None,
    ) -> ProjectInfo:
        """Find or register a project for the given workspace URI/path in Antigravity 2.0."""
        existing = self.match_project(workspace_uri_or_path)
        if existing:
            return existing

        local_path = self.uri_to_local_path(workspace_uri_or_path)
        if not display_name:
            # derive display name from directory basename
            base = os.path.basename(local_path.replace("/", "\\"))
            display_name = base if base else "Imported Project"

        new_id = str(uuid.uuid4())
        slug = self.make_slug(display_name)
        folder_uri = self.local_path_to_uri(local_path)

        new_proj = ProjectInfo(
            id=new_id,
            name=display_name,
            folder_uri=folder_uri,
            local_path=local_path,
            slug=slug,
        )

        # 1. Create config/projects/<new_id>.json
        self.config.config_projects_dir.mkdir(parents=True, exist_ok=True)
        proj_cfg_path = self.config.config_projects_dir / f"{new_id}.json"
        proj_data = {
            "id": new_id,
            "name": display_name,
            "projectResources": {
                "resources": [
                    {
                        "folderUri": folder_uri,
                    }
                ]
            },
            "settings": {},
            "isWorkspaceOnly": False,
        }
        with open(proj_cfg_path, "w", encoding="utf-8") as fp:
            json.dump(proj_data, fp, indent=2)

        # 2. Update projects.json
        if self.config.projects_json.exists():
            try:
                with open(self.config.projects_json, "r", encoding="utf-8") as fp:
                    pj_data = json.load(fp)
            except Exception:
                pj_data = {"projects": {}}
        else:
            pj_data = {"projects": {}}

        pj_data.setdefault("projects", {})[local_path] = slug
        with open(self.config.projects_json, "w", encoding="utf-8") as fp:
            json.dump(pj_data, fp, indent=2)

        # 3. Update recentlyOpenedPathsList in state.vscdb
        vscdb_path = self.config.app_vscdb_path
        if vscdb_path.exists():
            try:
                conn = sqlite3.connect(vscdb_path, timeout=10.0)
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key='history.recentlyOpenedPathsList';"
                ).fetchone()
                if row and row[0]:
                    recent = json.loads(row[0])
                    entries = recent.get("entries", [])
                    existing_uris = set(
                        e.get("folderUri", "").lower() for e in entries if "folderUri" in e
                    )
                    if folder_uri.lower() not in existing_uris:
                        entries.insert(0, {"folderUri": folder_uri})
                        recent["entries"] = entries
                        conn.execute(
                            "UPDATE ItemTable SET value=? WHERE key='history.recentlyOpenedPathsList';",
                            (json.dumps(recent),),
                        )
                        conn.commit()
                conn.close()
            except Exception:
                pass

        # Update cache
        self._projects[new_id] = new_proj
        self._path_to_id[local_path] = new_id
        self._uri_to_id[self.normalize_uri(folder_uri)] = new_id

        return new_proj
