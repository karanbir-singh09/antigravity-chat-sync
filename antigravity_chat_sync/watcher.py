"""Background watcher module for Antigravity IDE chats.
Monitors for new or modified conversations and triggers automatic synchronization.
"""

import threading
import time
from typing import Callable, Optional

from .chat_scanner import ChatScanner
from .config import SyncConfig, default_config
from .sync_engine import SyncEngine, SyncResult


class ChatWatcher:
    def __init__(
        self,
        scanner: Optional[ChatScanner] = None,
        sync_engine: Optional[SyncEngine] = None,
        interval_seconds: float = 5.0,
        on_sync_callback: Optional[Callable[[SyncResult], None]] = None,
    ):
        self.scanner = scanner or ChatScanner()
        self.sync_engine = sync_engine or SyncEngine()
        self.interval = interval_seconds
        self.on_sync_callback = on_sync_callback
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the background watcher thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background watcher."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while self._running:
            try:
                items = self.scanner.scan_all()
                pending = [it for it in items if it.is_pending]
                if pending:
                    result = self.sync_engine.sync_conversations(pending)
                    if self.on_sync_callback:
                        self.on_sync_callback(result)
            except Exception:
                pass

            # Sleep in small increments for responsive shutdown
            for _ in range(int(self.interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)
