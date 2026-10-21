"""Core sync engine that migrates conversations from Antigravity IDE to Antigravity 2.0.
Handles files, brain artifacts, sqlite databases, FTS index, protobuf state, project linking,
and project hierarchy grouping.
"""

import base64
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .backup_manager import BackupManager
from .chat_scanner import ConversationItem
from .config import SyncConfig, default_config
from .project_manager import ProjectManager
from .protobuf_utils import (
    inject_metadata_into_summary,
    merge_proto_summaries,
    parse_trajectory_summaries,
    wrap_summary_for_vscdb,
)


@dataclass
class SyncResult:
    total_requested: int = 0
    total_synced: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    synced_items: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    backup_paths: Dict[str, str] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.total_failed == 0


class SyncEngine:
    def __init__(
        self,
        config: SyncConfig = default_config,
        project_mgr: Optional[ProjectManager] = None,
        backup_mgr: Optional[BackupManager] = None,
    ):
        self.config = config
        self.project_mgr = project_mgr or ProjectManager(config)
        self.backup_mgr = backup_mgr or BackupManager(config)

    def _copy_conversation_file(self, item: ConversationItem) -> bool:
        """Copy conversation database or protobuf file from IDE to App directory."""
        cid = item.id
        suffix = item.file_type
        src = self.config.ide_convs_dir / f"{cid}{suffix}"
        dst = self.config.app_convs_dir / f"{cid}{suffix}"

        if not src.exists():
            return False

        self.config.app_convs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        # If sqlite db, also copy WAL and SHM if present in IDE
        if suffix == ".db":
            for ext in ("-wal", "-shm"):
                src_side = self.config.ide_convs_dir / f"{cid}.db{ext}"
                dst_side = self.config.app_convs_dir / f"{cid}.db{ext}"
                if src_side.exists():
                    try:
                        shutil.copy2(src_side, dst_side)
                    except Exception:
                        pass
        return True

    def _copy_brain_directory(self, cid: str) -> bool:
        """Copy brain directory (transcripts, artifacts, uploads, scratches) to App directory."""
        src_brain = self.config.ide_brain_dir / cid
        dst_brain = self.config.app_brain_dir / cid

        if not src_brain.exists():
            return False

        self.config.app_brain_dir.mkdir(parents=True, exist_ok=True)
        try:
            if dst_brain.exists():
                for root, dirs, files in os.walk(src_brain):
                    rel_path = os.path.relpath(root, src_brain)
                    target_dir = dst_brain / rel_path
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for f in files:
                        s_file = Path(root) / f
                        d_file = target_dir / f
                        if not d_file.exists() or s_file.stat().st_mtime > d_file.stat().st_mtime:
                            shutil.copy2(s_file, d_file)
            else:
                shutil.copytree(src_brain, dst_brain)
            return True
        except Exception:
            return False

    def _update_conversation_summaries_db(
        self,
        item: ConversationItem,
        project_id: str,
        workspace_json: str,
    ) -> bool:
        """Upsert conversation record in conversation_summaries.db with injected project_id."""
        db_path = self.config.app_summaries_db_path
        if not db_path.exists():
            return False

        mod_time = item.last_modified.strftime("%Y-%m-%d %H:%M:%S+00:00")
        clean_ws = item.workspace_uri

        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            cursor = conn.cursor()

            # Check existing row
            cursor.execute(
                "SELECT conversation_id, raw_summary FROM conversation_summaries WHERE conversation_id = ?;",
                (item.id,),
            )
            row = cursor.fetchone()

            raw_summary_to_use = item.raw_summary
            if not raw_summary_to_use and row and row[1]:
                raw_summary_to_use = row[1]

            # Inject project_id and workspace_uri into raw_summary protobuf
            if raw_summary_to_use:
                raw_summary_to_use = inject_metadata_into_summary(
                    raw_summary_to_use, project_id, clean_ws
                )
                item.raw_summary = raw_summary_to_use

            if row:
                cursor.execute(
                    """
                    UPDATE conversation_summaries
                    SET preview = ?,
                        step_count = ?,
                        last_modified_time = ?,
                        workspace_uris = ?,
                        project_id = ?,
                        raw_summary = ?,
                        last_user_input_time = ?,
                        app_data_dir = 'antigravity'
                    WHERE conversation_id = ?;
                """,
                    (
                        item.title,
                        item.step_count,
                        mod_time,
                        workspace_json,
                        project_id,
                        raw_summary_to_use,
                        mod_time,
                        item.id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO conversation_summaries (
                        conversation_id, title, preview, step_count, last_modified_time,
                        workspace_uris, status, source, project_id, agent_name,
                        parent_conversation_id, nesting_depth, battle_id, winning_conversation_id,
                        not_fully_idle, killed, last_user_input_time, last_user_input_step_index,
                        app_data_dir, raw_summary, group_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                    (
                        item.id,
                        "",
                        item.title,
                        item.step_count,
                        mod_time,
                        workspace_json,
                        "CASCADE_RUN_STATUS_IDLE",
                        "",
                        project_id,
                        "",
                        "",
                        0,
                        "",
                        "",
                        0,
                        0,
                        mod_time,
                        0,
                        "antigravity",
                        raw_summary_to_use,
                        "",
                    ),
                )

            # Update FTS index
            try:
                ws_name = ""
                try:
                    ws_list = json.loads(workspace_json)
                    if ws_list:
                        ws_name = ws_list[0].split("/")[-1]
                except Exception:
                    pass

                cursor.execute(
                    "DELETE FROM conversations_fts WHERE conversation_id = ?;",
                    (item.id,),
                )
                cursor.execute(
                    """
                    INSERT INTO conversations_fts (
                        conversation_id, chunk_index, chunk_first_step, chunk_last_step,
                        last_modified_time, step_count, last_step_created_at, archived,
                        user_step_byte_offsets, agent_step_byte_offsets, title,
                        workspace, project, user_body, agent_body
                    ) VALUES (?, 0, 0, ?, 0, ?, 0, 0, '', '', ?, ?, ?, ?, '');
                """,
                    (
                        item.id,
                        item.step_count,
                        item.step_count,
                        item.title,
                        ws_name,
                        ws_name,
                        item.title,
                    ),
                )
            except Exception:
                pass

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _sync_protobuf_stores(self, items_by_id: Dict[str, ConversationItem]) -> None:
        """Sync raw summaries into agyhub_summaries_proto.pb and state.vscdb with project_id injected."""
        new_summaries: Dict[str, bytes] = {}
        for cid, item in items_by_id.items():
            if item.raw_summary:
                injected = inject_metadata_into_summary(
                    item.raw_summary, item.project_id, item.workspace_uri
                )
                new_summaries[cid] = injected

        if not new_summaries:
            return

        # 1. Update agyhub_summaries_proto.pb (unwrapped raw protobuf)
        proto_path = self.config.app_proto_path
        existing_proto = b""
        if proto_path.exists():
            try:
                with open(proto_path, "rb") as f:
                    existing_proto = f.read()
            except Exception:
                pass

        try:
            merged_proto = merge_proto_summaries(
                existing_proto, new_summaries, wrap_for_vscdb=False
            )
            with open(proto_path, "wb") as f:
                f.write(merged_proto)
        except Exception:
            pass

        # 2. Update state.vscdb trajectorySummaries (wrapped base64 for VSCode extension host)
        vscdb_path = self.config.app_vscdb_path
        if vscdb_path.exists():
            try:
                conn = sqlite3.connect(vscdb_path, timeout=15.0)
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.trajectorySummaries';"
                ).fetchone()
                existing_bytes = b""
                if row and row[0]:
                    try:
                        val = row[0]
                        existing_bytes = base64.b64decode(val) if isinstance(val, str) else val
                    except Exception:
                        pass

                merged_bytes = merge_proto_summaries(
                    existing_bytes, new_summaries, wrap_for_vscdb=True
                )
                b64_val = base64.b64encode(merged_bytes).decode("ascii")
                conn.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('antigravityUnifiedStateSync.trajectorySummaries', ?);",
                    (b64_val,),
                )

                # Also sync sidebarWorkspaces from IDE if available
                ide_vscdb = self.config.ide_vscdb_path
                if ide_vscdb.exists():
                    try:
                        iconn = sqlite3.connect(ide_vscdb, timeout=5.0)
                        irow = iconn.execute(
                            "SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.sidebarWorkspaces';"
                        ).fetchone()
                        iconn.close()
                        if irow and irow[0]:
                            conn.execute(
                                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('antigravityUnifiedStateSync.sidebarWorkspaces', ?);",
                                (irow[0],),
                            )
                    except Exception:
                        pass

                conn.commit()
                conn.close()
            except Exception:
                pass

        # 3. Update app_storage.json (projectsOrder and uncollapse sidebar sections)
        app_storage = self.config.app_roaming / "app_storage.json"
        if app_storage.exists():
            try:
                with open(app_storage, "r", encoding="utf-8") as f:
                    storage = json.load(f)

                # Ensure project IDs are in projectsOrder
                all_pids = []
                cfg_dir = self.config.config_projects_dir
                if cfg_dir.exists():
                    for f_name in os.listdir(cfg_dir):
                        if f_name.endswith(".json"):
                            all_pids.append(f_name.replace(".json", ""))

                if all_pids:
                    storage["projectsOrder"] = json.dumps(all_pids)
                    storage["sidebar_collapsed_sections"] = "[]"

                with open(app_storage, "w", encoding="utf-8") as f:
                    json.dump(storage, f, indent=2)
            except Exception:
                pass

    def sync_conversations(
        self,
        items: List[ConversationItem],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> SyncResult:
        """Execute synchronization of the given conversations."""
        result = SyncResult(total_requested=len(items))
        if not items:
            return result

        # 1. Create safety snapshot
        if on_progress:
            on_progress(0, len(items), "Creating safety backup of databases...")
        result.backup_paths = self.backup_mgr.create_snapshot()

        synced_items_map: Dict[str, ConversationItem] = {}

        for i, item in enumerate(items, start=1):
            if on_progress:
                on_progress(i, len(items), f"Syncing ({i}/{len(items)}): {item.title[:40]}")

            try:
                # 2. Link or register project
                proj_id = "outside-of-project"
                ws_json = "[]"
                if item.workspace_uri:
                    clean_ws = item.workspace_uri.replace("\\", "/").rstrip('"').rstrip("'")
                    ws_json = f'["{clean_ws}"]'
                    proj = self.project_mgr.ensure_project(item.workspace_uri)
                    if proj:
                        proj_id = proj.id
                        item.project_id = proj.id
                        item.project_name = proj.name

                # 3. Copy conversation database / proto file
                copied_file = self._copy_conversation_file(item)
                if not copied_file:
                    result.errors.append(f"Failed to copy file for {item.id} ({item.title})")
                    result.total_failed += 1
                    continue

                # 4. Copy brain directory
                self._copy_brain_directory(item.id)

                # 5. Update conversation_summaries.db
                updated_db = self._update_conversation_summaries_db(item, proj_id, ws_json)
                if not updated_db:
                    result.errors.append(f"Failed to update database for {item.id}")
                    result.total_failed += 1
                    continue

                item.status = "SYNCED"
                synced_items_map[item.id] = item
                result.synced_items.append(item.id)
                result.total_synced += 1

            except Exception as e:
                result.errors.append(f"Error syncing {item.id}: {str(e)}")
                result.total_failed += 1

        # 6. Protobuf & unified state update in batch
        if synced_items_map:
            if on_progress:
                on_progress(len(items), len(items), "Updating protobuf & unified state registries...")
            self._sync_protobuf_stores(synced_items_map)

        if on_progress:
            on_progress(
                len(items),
                len(items),
                f"Sync complete! {result.total_synced} synced, {result.total_failed} errors.",
            )

        return result
