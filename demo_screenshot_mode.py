"""Demo / Screenshot Mode for Antigravity Chat Sync.
Launches the GUI pre-populated with mock, clean, generic conversations and projects
so you can take clean screenshots for GitHub, docs, or social media without revealing
any of your personal data or conversation history.
"""

import os
import sys
from datetime import datetime, timedelta

# Ensure package root is in sys.path
package_root = os.path.dirname(os.path.abspath(__file__))
if package_root not in sys.path:
    sys.path.insert(0, package_root)

from antigravity_chat_sync.chat_scanner import ConversationItem
from antigravity_chat_sync.gui.app import AntigravityChatSyncApp


def create_demo_items():
    now = datetime.now()
    demo_data = [
        # (title, project, status, steps, app_steps, file_type, age_minutes)
        (
            "Build full-stack dashboard with React, Tailwind, and FastAPI backend",
            "Dashboard-App",
            "NEW",
            24,
            0,
            ".db",
            5,
        ),
        (
            "Refactor authentication flow: migrate session cookies to OAuth2 JWT tokens",
            "Auth-Service",
            "UPDATED",
            42,
            38,
            ".db",
            18,
        ),
        (
            "Design custom CustomTkinter theme matching Google Antigravity dark palette",
            "UI-Components",
            "SYNCED",
            15,
            15,
            ".db",
            60,
        ),
        (
            "Fix protobuf serialization issue in trajectory metadata (Field 18 projectId)",
            "Core-Engine",
            "NEW",
            31,
            0,
            ".pb",
            90,
        ),
        (
            "Optimize SQLite queries and implement in-memory stat cache for file scanner",
            "Core-Engine",
            "UPDATED",
            19,
            12,
            ".db",
            140,
        ),
        (
            "Write comprehensive unit test suite covering SyncEngine, ChatScanner & BackupManager",
            "Testing-Suite",
            "SYNCED",
            28,
            28,
            ".db",
            240,
        ),
        (
            "Implement live background watcher for detecting new prompts every 5 seconds",
            "Core-Engine",
            "SYNCED",
            14,
            14,
            ".db",
            320,
        ),
        (
            "Setup Docker container and multi-stage build workflow for production deploy",
            "DevOps-Pipeline",
            "NEW",
            17,
            0,
            ".pb",
            450,
        ),
        (
            "Debug WebSocket real-time chat sync disconnects on high network latency",
            "Dashboard-App",
            "UPDATED",
            36,
            29,
            ".db",
            600,
        ),
        (
            "Setup automated database snapshots with instant one-click rollback modal",
            "Core-Engine",
            "SYNCED",
            22,
            22,
            ".db",
            820,
        ),
        (
            "Add debounced search input (220ms) and pagination controls for 60fps rendering",
            "UI-Components",
            "SYNCED",
            16,
            16,
            ".db",
            960,
        ),
        (
            "Design interactive biomolecular structure viewer sidecar integration",
            "Science-Plugin",
            "SYNCED",
            48,
            48,
            ".db",
            1200,
        ),
    ]

    items = []
    for idx, (title, proj, status, steps, app_steps, ftype, age) in enumerate(demo_data, 1):
        cid = f"demo-{idx:04d}-cortex-{status.lower()}-7f8a9b"
        mtime = now - timedelta(minutes=age)
        items.append(
            ConversationItem(
                id=cid,
                title=title,
                step_count=steps,
                app_step_count=app_steps,
                last_modified=mtime,
                workspace_uri=f"file:///c%3A/Projects/{proj}",
                project_id=f"proj-{proj.lower()}",
                project_name=proj,
                file_type=ftype,
                status=status,
                raw_summary=None,
                ide_file_size=1024 * steps * 2,
                app_file_size=1024 * app_steps * 2,
            )
        )
    return items


class DemoApp(AntigravityChatSyncApp):
    def refresh_scan(self):
        """Override scanner with mock data for clean screenshot mode."""
        self.status_label.configure(text="[DEMO MODE] Loaded sample conversations for screenshot.")
        items = create_demo_items()
        projects = sorted(list(set(it.project_name for it in items)))
        self._on_scan_completed(items, projects)

    def _run_sync_worker(self, targets):
        """Simulate sync without touching any real databases on disk."""
        self.is_syncing = True
        self.progress_bar.set(0)
        self.btn_sync_all.configure(state="disabled")
        self.btn_sync_selected.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")

        import time

        def sim():
            total = len(targets)
            for i, target in enumerate(targets, 1):
                time.sleep(0.3)
                pct = i / total
                self.after(
                    0,
                    lambda p=pct, t=target.title: self._update_progress(
                        p, f"[DEMO] Simulated sync: {t[:35]}..."
                    ),
                )
                target.status = "SYNCED"
                target.app_step_count = target.step_count

            time.sleep(0.2)
            self.after(
                0,
                lambda: self._on_sync_finished(
                    type("Result", (), {"is_success": True, "total_synced": total, "total_failed": 0})()
                ),
            )

        import threading

        threading.Thread(target=sim, daemon=True).start()


def main():
    app = DemoApp()
    app.title("Antigravity Chat Sync — [Screenshot / Demo Mode]")
    app.mainloop()


if __name__ == "__main__":
    main()
