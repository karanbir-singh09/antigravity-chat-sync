"""Scanner module for Antigravity IDE and Antigravity 2.0 chats.
Discovers conversations, extracts metadata, and categorizes sync status.
"""

import base64
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config import SyncConfig, default_config
from .project_manager import ProjectInfo, ProjectManager
from .protobuf_utils import (
    extract_summary_metadata,
    parse_protobuf_dict,
    parse_trajectory_summaries,
)


@dataclass
class ConversationItem:
    id: str
    title: str
    step_count: int
    last_modified: datetime
    workspace_uri: str = ""
    project_id: str = ""
    project_name: str = "Outside of Project"
    file_type: str = ".db"
    status: str = "NEW"  # "NEW", "UPDATED", "SYNCED"
    app_step_count: int = 0
    raw_summary: Optional[bytes] = None
    ide_file_size: int = 0
    app_file_size: int = 0

    @property
    def last_modified_str(self) -> str:
        return self.last_modified.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def is_pending(self) -> bool:
        return self.status in ("NEW", "UPDATED")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "step_count": self.step_count,
            "app_step_count": self.app_step_count,
            "last_modified": self.last_modified_str,
            "workspace_uri": self.workspace_uri,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "file_type": self.file_type,
            "status": self.status,
            "is_pending": self.is_pending,
        }


def clean_preview_text(text: str) -> str:
    """Sanitize and format raw prompt text into a clean single-line preview."""
    if not text:
        return ""
    text = text.strip()
    # Strip <USER_REQUEST> tags if present
    match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    elif "<USER_REQUEST>" in text:
        text = text.replace("<USER_REQUEST>", "").strip()

    # Strip XML metadata tags
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)

    # Normalize whitespace
    text = " ".join(text.split())

    # Strip leading noise
    if len(text) > 2 and text[0].isalpha() and text[1].isupper() and text[2].islower():
        # leading single uppercase letter artifact (e.g. "Tcan you" -> "can you")
        text = text[1:].strip()
    elif len(text) > 1 and text[0] in ("#", "@", ":", ";", "/", "-"):
        text = text[1:].strip()

    return text[:160]


class ChatScanner:
    def __init__(
        self,
        config: SyncConfig = default_config,
        project_mgr: Optional[ProjectManager] = None,
    ):
        self.config = config
        self.project_mgr = project_mgr or ProjectManager(config)
        self._meta_cache: Dict[str, Dict[str, Any]] = {}

    def clear_cache(self):
        """Clear cached metadata to force fresh disk parsing."""
        self._meta_cache.clear()

    def scan_app_conversations(self) -> Dict[str, Dict[str, Any]]:
        """Read all indexed conversations from Antigravity 2.0 DB."""
        app_chats: Dict[str, Dict[str, Any]] = {}
        db_path = self.config.app_summaries_db_path
        if not db_path.exists():
            return app_chats

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT conversation_id, title, preview, step_count,
                       last_modified_time, workspace_uris, project_id, raw_summary
                FROM conversation_summaries;
            """
            )
            for row in cursor.fetchall():
                cid, title, preview, steps, mtime, ws, pid, raw = row
                app_chats[cid] = {
                    "title": title or preview,
                    "step_count": steps or 0,
                    "last_modified_time": mtime,
                    "workspace_uris": ws,
                    "project_id": pid,
                    "has_raw_summary": bool(raw),
                }
            conn.close()
        except Exception:
            pass

        return app_chats

    def scan_ide_trajectory_summaries(self) -> Dict[str, bytes]:
        """Read raw protobuf summaries from IDE state.vscdb if available."""
        summaries: Dict[str, bytes] = {}
        vscdb_path = self.config.ide_vscdb_path
        if not vscdb_path.exists():
            return summaries

        try:
            conn = sqlite3.connect(f"file:{vscdb_path}?mode=ro", uri=True, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.trajectorySummaries';"
            )
            row = cursor.fetchone()
            if row and row[0]:
                val = row[0]
                if isinstance(val, str):
                    decoded = base64.b64decode(val)
                else:
                    decoded = val
                entries = parse_trajectory_summaries(decoded)
                for cid, raw in entries:
                    summaries[cid] = raw
            conn.close()
        except Exception:
            pass

        return summaries

    def extract_metadata_from_db(self, db_path: Path) -> Dict[str, Any]:
        """Extract steps and preview text directly from a conversation sqlite .db file."""
        meta = {
            "step_count": 0,
            "preview": "",
            "workspace_uri": "",
        }
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            cursor = conn.cursor()

            # 1. Step count
            try:
                cursor.execute("SELECT count(*) FROM steps;")
                meta["step_count"] = cursor.fetchone()[0]
            except Exception:
                pass

            # 2. First user prompt / payload
            try:
                cursor.execute(
                    "SELECT step_payload FROM steps WHERE step_payload IS NOT NULL ORDER BY idx ASC LIMIT 5;"
                )
                for (payload,) in cursor.fetchall():
                    if not payload:
                        continue
                    if isinstance(payload, bytes):
                        # Find USER_REQUEST tag
                        match = re.search(rb"<USER_REQUEST>(.*?)</USER_REQUEST>", payload, re.DOTALL)
                        if match:
                            meta["preview"] = match.group(1).decode("utf-8", errors="ignore").strip()
                            break
                        # Find workspace uri
                        if not meta["workspace_uri"]:
                            m = re.search(rb"file:///[^\s\x00-\x1f\x7f-\xff\"']+", payload)
                            if m:
                                meta["workspace_uri"] = m.group(0).decode("utf-8", errors="ignore")
                    elif isinstance(payload, str):
                        match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", payload, re.DOTALL)
                        if match:
                            meta["preview"] = match.group(1).strip()
                            break
            except Exception:
                pass

            # 3. Workspace from trajectory_metadata_blob if available
            if not meta["workspace_uri"]:
                try:
                    cursor.execute(
                        "SELECT data FROM trajectory_metadata_blob WHERE id='main';"
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        m = re.search(rb"file:///[^\s\x00-\x1f\x7f-\xff\"']+", row[0])
                        if m:
                            meta["workspace_uri"] = m.group(0).decode("utf-8", errors="ignore")
                except Exception:
                    pass

            conn.close()
        except Exception:
            pass

        return meta

    def extract_metadata_from_pb(self, pb_path: Path) -> Dict[str, Any]:
        """Extract steps and preview text from a protobuf .pb file."""
        meta = {
            "step_count": 0,
            "preview": "",
            "workspace_uri": "",
        }
        try:
            with open(pb_path, "rb") as f:
                data = f.read(25000)  # Read first chunk
            match = re.search(rb"<USER_REQUEST>(.*?)</USER_REQUEST>", data, re.DOTALL)
            if match:
                meta["preview"] = match.group(1).decode("utf-8", errors="ignore").strip()
            m = re.search(rb"file:///[^\s\x00-\x1f\x7f-\xff\"']+", data)
            if m:
                meta["workspace_uri"] = m.group(0).decode("utf-8", errors="ignore")
        except Exception:
            pass

        return meta

    def extract_from_brain(self, cid: str) -> Dict[str, Any]:
        """Fallback to inspect brain folder for transcript / overview."""
        meta = {
            "preview": "",
            "workspace_uri": "",
        }
        brain_dir = self.config.ide_brain_dir / cid
        if not brain_dir.exists():
            return meta

        overview_path = brain_dir / ".system_generated" / "logs" / "overview.txt"
        if overview_path.exists():
            try:
                with open(overview_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "USER_REQUEST" in line and not meta["preview"]:
                            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", line, re.DOTALL)
                            if m:
                                meta["preview"] = m.group(1).strip()
                        if "Active Document:" in line and not meta["workspace_uri"]:
                            m = re.search(r"Active Document:\s*(.*)", line)
                            if m:
                                meta["workspace_uri"] = m.group(1).strip()
            except Exception:
                pass

        return meta

    def scan_all(self) -> List[ConversationItem]:
        """Perform a full scan of all IDE conversations and compare against Antigravity 2.0."""
        app_chats = self.scan_app_conversations()
        ide_summaries = self.scan_ide_trajectory_summaries()

        items: List[ConversationItem] = []
        ide_convs_dir = self.config.ide_convs_dir

        if not ide_convs_dir.exists():
            return items

        # Gather all IDE conversation files (.db and .pb)
        found_cids: Set[str] = set()

        for f in ide_convs_dir.iterdir():
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            if suffix not in (".db", ".pb"):
                continue

            cid = f.stem
            # Ignore sqlite WAL/SHM sidecars
            if cid.endswith("-wal") or cid.endswith("-shm"):
                continue

            found_cids.add(cid)
            f_stat = f.stat()
            ide_size = f_stat.st_size
            ide_mtime_ts = f_stat.st_mtime
            ide_mtime = datetime.fromtimestamp(ide_mtime_ts)

            title = ""
            step_count = 0
            workspace_uri = ""
            raw_summary = ide_summaries.get(cid)

            # Check cache first for fast repeat scans (<5ms)
            cache_entry = self._meta_cache.get(cid)
            if cache_entry and cache_entry.get("mtime") == ide_mtime_ts and cache_entry.get("size") == ide_size:
                title = cache_entry["title"]
                step_count = cache_entry["step_count"]
                workspace_uri = cache_entry["workspace_uri"]
            else:
                # 1. Check if we have pre-computed summary from IDE state.vscdb
                if raw_summary:
                    sm = extract_summary_metadata(raw_summary)
                    if sm["title"]:
                        title = sm["title"]
                    if sm["step_count"]:
                        step_count = sm["step_count"]
                    if sm["workspace_uri"]:
                        workspace_uri = sm["workspace_uri"]

                # 2. If missing step_count or title, read from file
                if suffix == ".db":
                    db_meta = self.extract_metadata_from_db(f)
                    if not step_count and db_meta["step_count"]:
                        step_count = db_meta["step_count"]
                    if not title and db_meta["preview"]:
                        title = db_meta["preview"]
                    if not workspace_uri and db_meta["workspace_uri"]:
                        workspace_uri = db_meta["workspace_uri"]
                elif suffix == ".pb":
                    pb_meta = self.extract_metadata_from_pb(f)
                    if not title and pb_meta["preview"]:
                        title = pb_meta["preview"]
                    if not workspace_uri and pb_meta["workspace_uri"]:
                        workspace_uri = pb_meta["workspace_uri"]

                # 3. Brain check fallback
                if not title or not workspace_uri:
                    b_meta = self.extract_from_brain(cid)
                    if not title and b_meta["preview"]:
                        title = b_meta["preview"]
                    if not workspace_uri and b_meta["workspace_uri"]:
                        workspace_uri = b_meta["workspace_uri"]

                # Fallback title if still empty
                title = clean_preview_text(title)
                if not title:
                    title = f"IDE Chat ({cid[:8]})"

                # Store in cache
                self._meta_cache[cid] = {
                    "mtime": ide_mtime_ts,
                    "size": ide_size,
                    "title": title,
                    "step_count": step_count,
                    "workspace_uri": workspace_uri,
                }

            # Match project
            proj = self.project_mgr.match_project(workspace_uri)
            proj_id = proj.id if proj else "outside-of-project"
            proj_name = proj.name if proj else "Outside of Project"

            # Determine status against Antigravity 2.0
            app_info = app_chats.get(cid)
            app_file = self.config.app_convs_dir / f"{cid}{suffix}"
            app_size = app_file.stat().st_size if app_file.exists() else 0
            app_steps = app_info.get("step_count", 0) if app_info else 0

            if app_info is None or not app_file.exists():
                status = "NEW"
            elif step_count > app_steps or (ide_size > app_size and abs(ide_size - app_size) > 100):
                status = "UPDATED"
            else:
                status = "SYNCED"

            items.append(
                ConversationItem(
                    id=cid,
                    title=title,
                    step_count=step_count,
                    app_step_count=app_steps,
                    last_modified=ide_mtime,
                    workspace_uri=workspace_uri,
                    project_id=proj_id,
                    project_name=proj_name,
                    file_type=suffix,
                    status=status,
                    raw_summary=raw_summary,
                    ide_file_size=ide_size,
                    app_file_size=app_size,
                )
            )

        # Sort: pending (NEW/UPDATED) first, then by last modified descending
        items.sort(
            key=lambda item: (
                0 if item.status == "NEW" else (1 if item.status == "UPDATED" else 2),
                -item.last_modified.timestamp(),
            )
        )
        return items
