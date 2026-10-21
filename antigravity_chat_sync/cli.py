"""Command-line interface for Antigravity Chat Sync.
Allows terminal-based scanning, selective syncing, automated watching, and backup management.
"""

import argparse
import sys
import time
from typing import List

from .backup_manager import BackupManager
from .chat_scanner import ChatScanner, ConversationItem
from .config import SyncConfig, default_config
from .project_manager import ProjectManager
from .sync_engine import SyncEngine
from .watcher import ChatWatcher


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    """Format and print an ASCII table with aligned columns."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * widths[i] for i in range(len(headers)))
    data_lines = [
        " | ".join(str(val).ljust(widths[i]) for i, val in enumerate(row))
        for row in rows
    ]
    return f"{header_line}\n{sep_line}\n" + "\n".join(data_lines)


def run_scan(args, config: SyncConfig):
    scanner = ChatScanner(config)
    items = scanner.scan_all()
    if args.filter_status:
        items = [it for it in items if it.status.lower() == args.filter_status.lower()]
    if args.filter_project:
        items = [
            it
            for it in items
            if args.filter_project.lower() in it.project_name.lower()
        ]

    headers = ["Status", "Conversation ID", "Project", "Steps", "Type", "Title / Preview"]
    rows = []
    for it in items:
        status_tag = f"[{it.status}]"
        rows.append(
            [
                status_tag,
                it.id[:8] + "...",
                it.project_name[:16],
                str(it.step_count),
                it.file_type,
                it.title[:45],
            ]
        )

    print(f"\n--- Antigravity IDE Conversations (Total: {len(items)}) ---")
    if rows:
        print(format_table(headers, rows))
    else:
        print("No matching conversations found.")

    pending_count = sum(1 for it in items if it.is_pending)
    print(f"\nSummary: {pending_count} pending sync, {len(items) - pending_count} synced.\n")


def run_sync(args, config: SyncConfig):
    scanner = ChatScanner(config)
    engine = SyncEngine(config)
    items = scanner.scan_all()

    targets: List[ConversationItem] = []
    if args.cid:
        targets = [it for it in items if it.id.lower().startswith(args.cid.lower())]
        if not targets:
            print(f"Error: Conversation ID matching '{args.cid}' not found in IDE.")
            sys.exit(1)
    elif args.project:
        targets = [
            it
            for it in items
            if args.project.lower() in it.project_name.lower()
        ]
        if not targets:
            print(f"Error: No conversations found for project '{args.project}'.")
            sys.exit(1)
    elif args.force:
        targets = items
    else:
        targets = [it for it in items if it.is_pending]

    if not targets:
        print("Everything is up to date! No pending chats to sync.")
        return

    print(f"Preparing to sync {len(targets)} conversation(s) to Antigravity 2.0...")

    def progress_callback(cur, total, msg):
        bar_len = 25
        percent = (cur / total) if total else 1.0
        filled = int(bar_len * percent)
        bar = "#" * filled + "-" * (bar_len - filled)
        sys.stdout.write(f"\r[{bar}] {int(percent*100)}% - {msg[:50].ljust(50)}")
        sys.stdout.flush()

    res = engine.sync_conversations(targets, on_progress=progress_callback)
    print("\n")
    if res.is_success:
        print(f"SUCCESS: Successfully synced {res.total_synced} conversation(s)!")
        if res.backup_paths:
            print(f"Backup created: {list(res.backup_paths.values())[0]}")
        print("\nTip: Press Ctrl+R in Antigravity 2.0 to immediately refresh your sidebar.")
    else:
        print(
            f"WARNING: Synced {res.total_synced} items, but {res.total_failed} item(s) failed."
        )
        for err in res.errors:
            print(f"  - {err}")


def run_watch(args, config: SyncConfig):
    scanner = ChatScanner(config)
    engine = SyncEngine(config)

    def on_sync(result):
        now_str = time.strftime("%H:%M:%S")
        print(
            f"[{now_str}] Auto-synced {result.total_synced} chat(s) from IDE to Antigravity 2.0!"
        )

    watcher = ChatWatcher(
        scanner, engine, interval_seconds=args.interval, on_sync_callback=on_sync
    )
    watcher.start()
    print(
        f"Watching Antigravity IDE conversations every {args.interval}s for changes... (Press Ctrl+C to stop)"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watcher...")
        watcher.stop()


def run_backups(args, config: SyncConfig):
    mgr = BackupManager(config)
    if args.restore:
        success = mgr.restore_backup(args.restore)
        if success:
            print(f"Successfully restored database from: {args.restore}")
        else:
            print(f"Failed to restore backup: file not found or invalid.")
        return

    backups = mgr.list_backups()
    if not backups:
        print("No backups found.")
        return

    headers = ["Type", "Filename", "Size (KB)", "Date / Time"]
    rows = [
        [b["type"], b["filename"], f"{b['size_bytes'] / 1024:.1f}", b["timestamp"]]
        for b in backups
    ]
    print("\n--- Available Database Backups ---")
    print(format_table(headers, rows))
    print("\nTo restore, run: python run_cli.py backups --restore <backup_filepath>\n")


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity Chat Sync - Bridge chats from IDE to Antigravity 2.0"
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # scan
    scan_p = subparsers.add_parser("scan", aliases=["list"], help="Scan and list IDE chats")
    scan_p.add_argument("--status", dest="filter_status", help="Filter by status (NEW, UPDATED, SYNCED)")
    scan_p.add_argument("--project", dest="filter_project", help="Filter by project name")

    # sync
    sync_p = subparsers.add_parser("sync", help="Sync chats to Antigravity 2.0")
    sync_p.add_argument("--cid", help="Sync specific conversation ID")
    sync_p.add_argument("--project", help="Sync all conversations for a project")
    sync_p.add_argument("--force", action="store_true", help="Force re-sync even if already synced")

    # watch
    watch_p = subparsers.add_parser("watch", help="Continuously monitor and auto-sync in background")
    watch_p.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")

    # backups
    back_p = subparsers.add_parser("backups", help="List or restore backups")
    back_p.add_argument("--restore", help="Path of backup file to restore")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command in ("scan", "list"):
        run_scan(args, default_config)
    elif args.command == "sync":
        run_sync(args, default_config)
    elif args.command == "watch":
        run_watch(args, default_config)
    elif args.command == "backups":
        run_backups(args, default_config)


if __name__ == "__main__":
    main()
