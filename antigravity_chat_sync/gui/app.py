"""Main GUI application for Antigravity Chat Sync.
Built with CustomTkinter for a modern, responsive, dark-mode pair-programming assistant UI.
Optimized for 60fps responsiveness with search debouncing, pagination, and dual Cards/Table views.
"""

import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Set

import customtkinter as ctk

from ..backup_manager import BackupManager
from ..chat_scanner import ChatScanner, ConversationItem
from ..config import SyncConfig, default_config
from ..project_manager import ProjectManager
from ..sync_engine import SyncEngine, SyncResult
from ..watcher import ChatWatcher
from .theme import (
    BG_DARK,
    BORDER_COLOR,
    PRIMARY_BLUE,
    PRIMARY_HOVER,
    STATUS_COLORS,
    SUCCESS_GREEN,
    SURFACE_DARK,
    SURFACE_LIGHTER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_AMBER,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AntigravityChatSyncApp(ctk.CTk):
    def __init__(self, config: SyncConfig = default_config):
        super().__init__()

        self.config = config
        self.project_mgr = ProjectManager(config)
        self.scanner = ChatScanner(config, self.project_mgr)
        self.backup_mgr = BackupManager(config)
        self.engine = SyncEngine(config, self.project_mgr, self.backup_mgr)
        self.watcher: Optional[ChatWatcher] = None

        # Data & Filter State
        self.all_items: List[ConversationItem] = []
        self.filtered_items: List[ConversationItem] = []
        self.selected_cids: Set[str] = set()
        self.is_syncing: bool = False

        # Performance, Pagination & View State
        self.view_mode: str = "cards"  # "cards" or "table"
        self.current_page: int = 1
        self.page_size: int = 20  # 20, 50, 100, or 0 (All)
        self.card_checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        self._search_timer: Optional[str] = None
        self.sort_column: str = "status"
        self.sort_descending: bool = False

        # Window Setup
        self.title("Antigravity Chat Sync (IDE → 2.0)")
        self.geometry("1140x780")
        self.minsize(920, 640)
        self.configure(fg_color=BG_DARK)

        self._configure_ttk_styles()
        self._build_ui()
        self.refresh_scan()

    def _configure_ttk_styles(self):
        """Configure native ttk styles for high-performance dark Table view."""
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure(
            "Dark.Treeview",
            background="#1e2024",
            foreground=TEXT_PRIMARY,
            fieldbackground="#1e2024",
            rowheight=32,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        self.style.configure(
            "Dark.Treeview.Heading",
            background=SURFACE_DARK,
            foreground=TEXT_SECONDARY,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padding=(10, 8),
        )
        self.style.map(
            "Dark.Treeview",
            background=[("selected", PRIMARY_HOVER)],
            foreground=[("selected", "#ffffff")],
        )
        self.style.map(
            "Dark.Treeview.Heading",
            background=[("active", SURFACE_LIGHTER)],
        )

    def _build_ui(self):
        # 1. Header Frame
        self.header_frame = ctk.CTkFrame(self, fg_color=SURFACE_DARK, corner_radius=0)
        self.header_frame.pack(fill="x", padx=0, pady=0)

        header_content = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        header_content.pack(fill="x", padx=24, pady=16)

        title_col = ctk.CTkFrame(header_content, fg_color="transparent")
        title_col.pack(side="left")

        app_title = ctk.CTkLabel(
            title_col,
            text="✨ Antigravity Chat Sync",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        app_title.pack(anchor="w")

        app_sub = ctk.CTkLabel(
            title_col,
            text="Bridge and sync conversations seamlessly from Antigravity IDE to Antigravity 2.0",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        )
        app_sub.pack(anchor="w")

        # Stats Cards on Right
        self.stats_frame = ctk.CTkFrame(header_content, fg_color="transparent")
        self.stats_frame.pack(side="right")

        self.stat_ide = self._create_stat_badge(self.stats_frame, "IDE Chats", "0", TEXT_PRIMARY)
        self.stat_pending = self._create_stat_badge(
            self.stats_frame, "Pending Sync", "0", WARNING_AMBER
        )
        self.stat_synced = self._create_stat_badge(
            self.stats_frame, "Synced in 2.0", "0", SUCCESS_GREEN
        )

        # 2. Action Controls Toolbar
        self.toolbar_frame = ctk.CTkFrame(self, fg_color=SURFACE_DARK, corner_radius=10)
        self.toolbar_frame.pack(fill="x", padx=24, pady=(12, 6))

        toolbar_content = ctk.CTkFrame(self.toolbar_frame, fg_color="transparent")
        toolbar_content.pack(fill="x", padx=16, pady=10)

        # Left Buttons
        self.btn_sync_all = ctk.CTkButton(
            toolbar_content,
            text="🚀 Sync All Pending (0)",
            command=self.sync_all_pending,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=PRIMARY_BLUE,
            hover_color=PRIMARY_HOVER,
            height=34,
        )
        self.btn_sync_all.pack(side="left", padx=(0, 10))

        self.btn_sync_selected = ctk.CTkButton(
            toolbar_content,
            text="⚡ Sync Selected (0)",
            command=self.sync_selected,
            font=ctk.CTkFont(size=13),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            height=34,
        )
        self.btn_sync_selected.pack(side="left", padx=(0, 10))

        self.btn_refresh = ctk.CTkButton(
            toolbar_content,
            text="🔄 Refresh",
            command=self.refresh_scan,
            font=ctk.CTkFont(size=13),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            width=90,
            height=34,
        )
        self.btn_refresh.pack(side="left", padx=(0, 10))

        # Right Action Buttons
        self.btn_open_folder = ctk.CTkButton(
            toolbar_content,
            text="📁 Data Folders",
            command=self.open_data_folder,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            hover_color=SURFACE_LIGHTER,
            height=34,
            width=110,
        )
        self.btn_open_folder.pack(side="right", padx=(6, 0))

        self.btn_backups = ctk.CTkButton(
            toolbar_content,
            text="🛡️ Backups",
            command=self.show_backups_modal,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            hover_color=SURFACE_LIGHTER,
            height=34,
            width=100,
        )
        self.btn_backups.pack(side="right", padx=(6, 0))

        # Auto-Sync Switch
        self.auto_sync_var = ctk.BooleanVar(value=False)
        self.switch_auto_sync = ctk.CTkSwitch(
            toolbar_content,
            text="Auto-Sync",
            variable=self.auto_sync_var,
            command=self.toggle_auto_sync,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        )
        self.switch_auto_sync.pack(side="right", padx=(0, 16))

        # 3. Filter and View Bar
        self.filter_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.filter_frame.pack(fill="x", padx=24, pady=(4, 6))

        # Search Entry with Debounce
        self.search_entry = ctk.CTkEntry(
            self.filter_frame,
            placeholder_text="🔍 Search title, prompt text, UUID, or project... (instant debounce)",
            height=34,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_DARK,
            border_color=BORDER_COLOR,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self._on_search_key_released)
        self.search_entry.bind("<Return>", lambda e: self.apply_filters())

        # Status filter
        self.status_var = ctk.StringVar(value="All Statuses")
        self.status_dropdown = ctk.CTkOptionMenu(
            self.filter_frame,
            values=["All Statuses", "Pending Only (New & Updated)", "New Only", "Updated Only", "Synced Only"],
            variable=self.status_var,
            command=lambda val: self.apply_filters(),
            width=185,
            height=34,
            fg_color=SURFACE_DARK,
            button_color=SURFACE_LIGHTER,
            button_hover_color="#3e4249",
        )
        self.status_dropdown.pack(side="left", padx=(0, 10))

        # Project filter
        self.project_var = ctk.StringVar(value="All Projects")
        self.project_dropdown = ctk.CTkOptionMenu(
            self.filter_frame,
            values=["All Projects"],
            variable=self.project_var,
            command=lambda val: self.apply_filters(),
            width=165,
            height=34,
            fg_color=SURFACE_DARK,
            button_color=SURFACE_LIGHTER,
            button_hover_color="#3e4249",
        )
        self.project_dropdown.pack(side="left", padx=(0, 10))

        # View Mode Switcher: Cards vs Table
        self.view_mode_segmented = ctk.CTkSegmentedButton(
            self.filter_frame,
            values=["📇 Cards", "📋 Table"],
            command=self._on_view_mode_changed,
            height=34,
            selected_color=PRIMARY_BLUE,
            selected_hover_color=PRIMARY_HOVER,
            unselected_color=SURFACE_DARK,
            unselected_hover_color=SURFACE_LIGHTER,
        )
        self.view_mode_segmented.set("📇 Cards")
        self.view_mode_segmented.pack(side="left")

        # 4. Selection Row & Range Info
        self.select_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.select_bar.pack(fill="x", padx=26, pady=(0, 4))

        self.select_all_var = ctk.BooleanVar(value=False)
        self.select_all_checkbox = ctk.CTkCheckBox(
            self.select_bar,
            text="Select All Matching",
            variable=self.select_all_var,
            command=self.toggle_select_all,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            height=20,
        )
        self.select_all_checkbox.pack(side="left")

        self.count_label = ctk.CTkLabel(
            self.select_bar,
            text="Showing 0 chats",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self.count_label.pack(side="right")

        # 5. Main Content Area (Containers for Cards & Table)
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=24, pady=(0, 6))

        # --- A. Cards Container ---
        self.cards_container = ctk.CTkFrame(self.main_container, fg_color="transparent")

        self.scroll_frame = ctk.CTkScrollableFrame(
            self.cards_container,
            fg_color="transparent",
            corner_radius=8,
        )
        self.scroll_frame.pack(fill="both", expand=True, pady=(0, 6))

        # Pagination Bar
        self.pagination_frame = ctk.CTkFrame(self.cards_container, fg_color=SURFACE_DARK, corner_radius=8, height=40)
        self.pagination_frame.pack(fill="x")

        pag_inner = ctk.CTkFrame(self.pagination_frame, fg_color="transparent")
        pag_inner.pack(fill="x", padx=12, pady=6)

        # Left Nav Buttons
        self.btn_first_page = ctk.CTkButton(
            pag_inner,
            text="⏮",
            width=34,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            command=self.go_first_page,
        )
        self.btn_first_page.pack(side="left", padx=(0, 4))

        self.btn_prev_page = ctk.CTkButton(
            pag_inner,
            text="◀ Prev",
            width=65,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            command=self.go_prev_page,
        )
        self.btn_prev_page.pack(side="left", padx=(0, 10))

        self.lbl_page_info = ctk.CTkLabel(
            pag_inner,
            text="Page 1 of 1",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.lbl_page_info.pack(side="left", padx=(0, 10))

        self.btn_next_page = ctk.CTkButton(
            pag_inner,
            text="Next ▶",
            width=65,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            command=self.go_next_page,
        )
        self.btn_next_page.pack(side="left", padx=(0, 4))

        self.btn_last_page = ctk.CTkButton(
            pag_inner,
            text="⏭",
            width=34,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            command=self.go_last_page,
        )
        self.btn_last_page.pack(side="left", padx=(0, 16))

        # Middle Range Label
        self.lbl_range_info = ctk.CTkLabel(
            pag_inner,
            text="Showing 0–0 of 0 chats",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        )
        self.lbl_range_info.pack(side="left")

        # Right Page Size Selector
        self.page_size_menu = ctk.CTkOptionMenu(
            pag_inner,
            values=["20 per page", "50 per page", "100 per page", "Show All"],
            command=self.on_page_size_changed,
            width=125,
            height=28,
            fg_color=SURFACE_LIGHTER,
            button_color="#3e4249",
            button_hover_color="#4b5058",
            font=ctk.CTkFont(size=11),
        )
        self.page_size_menu.set("20 per page")
        self.page_size_menu.pack(side="right")

        ctk.CTkLabel(
            pag_inner,
            text="Page size:",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        ).pack(side="right", padx=(0, 6))

        # --- B. Table Container (Ultra-Fast 2ms View) ---
        self.table_container = ctk.CTkFrame(self.main_container, fg_color=SURFACE_DARK, corner_radius=8)

        # Treeview with columns
        cols = ("status", "title", "project", "steps", "mtime")
        self.tree = ttk.Treeview(
            self.table_container,
            style="Dark.Treeview",
            columns=cols,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("status", text="Status  ↕", command=lambda: self._sort_by_column("status"))
        self.tree.heading("title", text="Conversation Title / Prompt  ↕", command=lambda: self._sort_by_column("title"))
        self.tree.heading("project", text="Project  ↕", command=lambda: self._sort_by_column("project"))
        self.tree.heading("steps", text="Steps  ↕", command=lambda: self._sort_by_column("steps"))
        self.tree.heading("mtime", text="Last Modified  ↕", command=lambda: self._sort_by_column("mtime"))

        self.tree.column("status", width=110, anchor="center")
        self.tree.column("title", width=460, anchor="w")
        self.tree.column("project", width=170, anchor="w")
        self.tree.column("steps", width=95, anchor="center")
        self.tree.column("mtime", width=145, anchor="center")

        self.tree.tag_configure("NEW", foreground=SUCCESS_GREEN)
        self.tree.tag_configure("UPDATED", foreground=WARNING_AMBER)
        self.tree.tag_configure("SYNCED", foreground=TEXT_SECONDARY)

        self.tree_scroll = ctk.CTkScrollbar(self.table_container, command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        self.tree_scroll.pack(side="right", fill="y", padx=2, pady=2)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Show initial view (Cards)
        self.cards_container.pack(fill="both", expand=True)

        # 6. Bottom Status & Progress Bar
        self.bottom_frame = ctk.CTkFrame(self, fg_color=SURFACE_DARK, corner_radius=0, height=48)
        self.bottom_frame.pack(fill="x", side="bottom")

        bottom_content = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        bottom_content.pack(fill="x", padx=24, pady=8)

        self.status_label = ctk.CTkLabel(
            bottom_content,
            text="Ready. Press 'Sync All Pending' to copy chats into Antigravity 2.0.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        )
        self.status_label.pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(
            bottom_content,
            width=260,
            height=10,
            fg_color=SURFACE_LIGHTER,
            progress_color=PRIMARY_BLUE,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(side="right")

    def _create_stat_badge(self, parent, label: str, val: str, val_color: str):
        card = ctk.CTkFrame(parent, fg_color=SURFACE_LIGHTER, corner_radius=8)
        card.pack(side="left", padx=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=12, pady=6)

        num = ctk.CTkLabel(
            inner,
            text=val,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=val_color,
        )
        num.pack()

        lbl = ctk.CTkLabel(
            inner,
            text=label,
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        )
        lbl.pack()
        return num

    # ---------------------------------------------------------
    # View Switching & Sorting
    # ---------------------------------------------------------
    def _on_view_mode_changed(self, choice: str):
        if "Table" in choice:
            self.view_mode = "table"
            self.cards_container.pack_forget()
            self.table_container.pack(fill="both", expand=True)
        else:
            self.view_mode = "cards"
            self.table_container.pack_forget()
            self.cards_container.pack(fill="both", expand=True)
        self._render_current_view()

    def _sort_by_column(self, col: str):
        if self.sort_column == col:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = col
            self.sort_descending = False

        def sort_key(it: ConversationItem):
            if col == "status":
                order = {"NEW": 0, "UPDATED": 1, "SYNCED": 2}
                return order.get(it.status, 3)
            elif col == "title":
                return it.title.lower()
            elif col == "project":
                return it.project_name.lower()
            elif col == "steps":
                return it.step_count
            elif col == "mtime":
                return it.last_modified.timestamp()
            return 0

        self.filtered_items.sort(key=sort_key, reverse=self.sort_descending)
        self._render_current_view()

    # ---------------------------------------------------------
    # Debounced Search & Filtering
    # ---------------------------------------------------------
    def _on_search_key_released(self, event):
        """Debounce search so typing does not freeze the UI."""
        if event and event.keysym in ("Return", "KP_Enter"):
            if self._search_timer:
                self.after_cancel(self._search_timer)
                self._search_timer = None
            self.apply_filters()
            return

        # Skip navigation and modifier keys
        if event and event.keysym in (
            "Up", "Down", "Left", "Right", "Control_L", "Control_R",
            "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Caps_Lock", "Tab"
        ):
            return

        if self._search_timer:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(220, self.apply_filters)

    def refresh_scan(self):
        """Perform a background scan and update the UI."""
        if self.is_syncing:
            return

        self.status_label.configure(text="Scanning Antigravity IDE and 2.0 conversations...")
        self.btn_refresh.configure(state="disabled")

        def worker():
            items = self.scanner.scan_all()
            projects = sorted(list(set(it.project_name for it in items)))
            try:
                self.after(0, lambda: self._on_scan_completed(items, projects))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_completed(self, items: List[ConversationItem], projects: List[str]):
        self.all_items = items
        self.btn_refresh.configure(state="normal")

        # Update Project Dropdown values
        proj_vals = ["All Projects"] + projects
        self.project_dropdown.configure(values=proj_vals)

        # Update Stats
        total_ide = len(items)
        pending = sum(1 for it in items if it.is_pending)
        synced = sum(1 for it in items if it.status == "SYNCED")

        self.stat_ide.configure(text=str(total_ide))
        self.stat_pending.configure(text=str(pending))
        self.stat_synced.configure(text=str(synced))

        self.btn_sync_all.configure(text=f"🚀 Sync All Pending ({pending})")
        if pending == 0:
            self.btn_sync_all.configure(fg_color=SURFACE_LIGHTER, hover_color="#3e4249")
        else:
            self.btn_sync_all.configure(fg_color=PRIMARY_BLUE, hover_color=PRIMARY_HOVER)

        self.status_label.configure(
            text=f"Scan complete. {total_ide} chats found ({pending} pending sync)."
        )
        self.apply_filters()

    def apply_filters(self):
        """Filter chats according to search query, status dropdown, and project dropdown."""
        query = self.search_entry.get().strip().lower()
        st_filter = self.status_var.get()
        proj_filter = self.project_var.get()

        filtered = []
        for it in self.all_items:
            # Query match
            if query:
                if (
                    query not in it.title.lower()
                    and query not in it.id.lower()
                    and query not in it.project_name.lower()
                    and query not in it.workspace_uri.lower()
                ):
                    continue

            # Status match
            if st_filter == "Pending Only (New & Updated)" and not it.is_pending:
                continue
            elif st_filter == "New Only" and it.status != "NEW":
                continue
            elif st_filter == "Updated Only" and it.status != "UPDATED":
                continue
            elif st_filter == "Synced Only" and it.status != "SYNCED":
                continue

            # Project match
            if proj_filter != "All Projects" and it.project_name != proj_filter:
                continue

            filtered.append(it)

        self.filtered_items = filtered
        self.current_page = 1
        self.count_label.configure(
            text=f"Showing {len(filtered)} of {len(self.all_items)} chats"
        )
        self._render_current_view()

    def _render_current_view(self):
        """Render whichever view is active (Cards or Table)."""
        if self.view_mode == "cards":
            self._render_conversation_cards()
            self._update_pagination_controls()
        else:
            self._render_table_rows()

    # ---------------------------------------------------------
    # Pagination Logic
    # ---------------------------------------------------------
    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, math.ceil(len(self.filtered_items) / self.page_size))

    def _get_page_items(self) -> List[ConversationItem]:
        if self.page_size <= 0:
            return self.filtered_items
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        return self.filtered_items[start_idx:end_idx]

    def _update_pagination_controls(self):
        tot = self.total_pages
        if self.current_page > tot:
            self.current_page = tot
        if self.current_page < 1:
            self.current_page = 1

        total_count = len(self.filtered_items)
        if total_count == 0:
            self.lbl_page_info.configure(text="Page 1 of 1")
            self.lbl_range_info.configure(text="Showing 0 chats")
            self.btn_first_page.configure(state="disabled")
            self.btn_prev_page.configure(state="disabled")
            self.btn_next_page.configure(state="disabled")
            self.btn_last_page.configure(state="disabled")
            return

        if self.page_size > 0:
            start_idx = (self.current_page - 1) * self.page_size + 1
            end_idx = min(start_idx + self.page_size - 1, total_count)
        else:
            start_idx = 1
            end_idx = total_count

        self.lbl_page_info.configure(text=f"Page {self.current_page} of {tot}")
        self.lbl_range_info.configure(text=f"Showing {start_idx}–{end_idx} of {total_count} chats")

        self.btn_first_page.configure(state="normal" if self.current_page > 1 else "disabled")
        self.btn_prev_page.configure(state="normal" if self.current_page > 1 else "disabled")
        self.btn_next_page.configure(state="normal" if self.current_page < tot else "disabled")
        self.btn_last_page.configure(state="normal" if self.current_page < tot else "disabled")

    def go_first_page(self):
        if self.current_page != 1:
            self.current_page = 1
            self._render_current_view()

    def go_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._render_current_view()

    def go_next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._render_current_view()

    def go_last_page(self):
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self._render_current_view()

    def on_page_size_changed(self, choice: str):
        if "20" in choice:
            self.page_size = 20
        elif "50" in choice:
            self.page_size = 50
        elif "100" in choice:
            self.page_size = 100
        elif "All" in choice:
            self.page_size = 0
        self.current_page = 1
        self._render_current_view()

    # ---------------------------------------------------------
    # Render Cards (Paginated)
    # ---------------------------------------------------------
    def _render_conversation_cards(self):
        """Render card list into scroll frame (only current page items)."""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.card_checkbox_vars.clear()

        # Scroll to top of canvas
        try:
            self.scroll_frame._parent_canvas.yview_moveto(0)
        except Exception:
            pass

        items_to_render = self._get_page_items()
        if not items_to_render:
            empty_card = ctk.CTkFrame(
                self.scroll_frame, fg_color=SURFACE_DARK, corner_radius=10
            )
            empty_card.pack(fill="x", padx=4, pady=16)
            ctk.CTkLabel(
                empty_card,
                text="No conversations matched the current search/filter.",
                font=ctk.CTkFont(size=13),
                text_color=TEXT_MUTED,
            ).pack(pady=24)
            return

        for item in items_to_render:
            self._create_card(item)

    def _create_card(self, item: ConversationItem):
        card = ctk.CTkFrame(
            self.scroll_frame,
            fg_color=SURFACE_DARK,
            border_color=BORDER_COLOR if item.status == "SYNCED" else (PRIMARY_BLUE if item.status == "NEW" else WARNING_AMBER),
            border_width=1,
            corner_radius=10,
        )
        card.pack(fill="x", padx=4, pady=4)

        # High-performance lightweight inner container
        card_content = tk.Frame(card, bg=SURFACE_DARK)
        card_content.pack(fill="x", padx=14, pady=9)

        # Left Checkbox
        chk_var = ctk.BooleanVar(value=item.id in self.selected_cids)
        self.card_checkbox_vars[item.id] = chk_var

        def on_chk_toggle():
            if chk_var.get():
                self.selected_cids.add(item.id)
            else:
                self.selected_cids.discard(item.id)
            self._update_selected_button()

        chk = ctk.CTkCheckBox(
            card_content,
            text="",
            variable=chk_var,
            command=on_chk_toggle,
            width=24,
            checkbox_width=20,
            checkbox_height=20,
            bg_color=SURFACE_DARK,
        )
        chk.pack(side="left", padx=(0, 12))

        # Center Details Column
        center = tk.Frame(card_content, bg=SURFACE_DARK)
        center.pack(side="left", fill="x", expand=True)

        # Top Badge Row
        badge_row = tk.Frame(center, bg=SURFACE_DARK)
        badge_row.pack(fill="x", anchor="w", pady=(0, 2))

        st_cfg = STATUS_COLORS.get(item.status, STATUS_COLORS["SYNCED"])
        status_pill = tk.Label(
            badge_row,
            text=f" {st_cfg['label']} ",
            font=("Segoe UI", 8, "bold"),
            fg=st_cfg["fg"],
            bg=st_cfg["bg"],
            padx=4,
            pady=1,
        )
        status_pill.pack(side="left", padx=(0, 8))

        proj_pill = tk.Label(
            badge_row,
            text=f" 📁 {item.project_name} ",
            font=("Segoe UI", 8),
            fg=TEXT_PRIMARY,
            bg=SURFACE_LIGHTER,
            padx=4,
            pady=1,
        )
        proj_pill.pack(side="left", padx=(0, 8))

        type_pill = tk.Label(
            badge_row,
            text=f" {item.file_type} ",
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=SURFACE_DARK,
        )
        type_pill.pack(side="left")

        # Title Label
        title_lbl = tk.Label(
            center,
            text=item.title,
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=SURFACE_DARK,
            anchor="w",
            justify="left",
        )
        title_lbl.pack(fill="x", anchor="w", pady=(1, 2))

        # Meta Info Row
        steps_text = f"💬 {item.step_count} steps"
        if item.status == "UPDATED" and item.app_step_count:
            steps_text += f" (2.0 has {item.app_step_count})"

        meta_lbl = tk.Label(
            center,
            text=f"{steps_text}   •   🕒 {item.last_modified_str}   •   ID: {item.id[:8]}...",
            font=("Segoe UI", 9),
            fg=TEXT_MUTED,
            bg=SURFACE_DARK,
            anchor="w",
        )
        meta_lbl.pack(fill="x", anchor="w")

        # Right Action Button
        action_btn_text = "Sync Now" if item.is_pending else "Re-Sync"
        action_btn_fg = PRIMARY_BLUE if item.is_pending else SURFACE_LIGHTER
        action_btn = ctk.CTkButton(
            card_content,
            text=action_btn_text,
            command=lambda it=item: self.sync_single_chat(it),
            font=ctk.CTkFont(size=11),
            fg_color=action_btn_fg,
            hover_color=PRIMARY_HOVER if item.is_pending else "#3e4249",
            width=90,
            height=28,
            bg_color=SURFACE_DARK,
        )
        action_btn.pack(side="right", padx=(10, 0))

    # ---------------------------------------------------------
    # Render Table View (Ultra-fast 2ms)
    # ---------------------------------------------------------
    def _render_table_rows(self):
        """Populate the fast native Treeview table with all filtered items."""
        # Save selection
        prev_selection = set(self.selected_cids)

        self.tree.delete(*self.tree.get_children())
        for it in self.filtered_items:
            st_symbol = "● NEW" if it.status == "NEW" else ("● UPDATED" if it.status == "UPDATED" else "✓ SYNCED")
            steps_display = f"{it.step_count}"
            if it.status == "UPDATED" and it.app_step_count:
                steps_display += f" (2.0: {it.app_step_count})"

            self.tree.insert(
                "",
                "end",
                iid=it.id,
                values=(st_symbol, it.title, it.project_name, steps_display, it.last_modified_str),
                tags=(it.status,),
            )

        # Restore tree selection
        matched_selection = [cid for cid in prev_selection if self.tree.exists(cid)]
        if matched_selection:
            self.tree.selection_set(matched_selection)

    def _on_tree_selection_changed(self, event):
        """Update selected cids when rows are clicked in the table."""
        selected = set(self.tree.selection())
        self.selected_cids = selected
        self._update_selected_button()

    def _on_tree_double_click(self, event):
        """Double clicking a row immediately syncs that conversation."""
        sel = self.tree.selection()
        if not sel:
            return
        cid = sel[0]
        match = next((it for it in self.all_items if it.id == cid), None)
        if match:
            self.sync_single_chat(match)

    # ---------------------------------------------------------
    # Selection and Sync Actions
    # ---------------------------------------------------------
    def _update_selected_button(self):
        count = len(self.selected_cids)
        self.btn_sync_selected.configure(text=f"⚡ Sync Selected ({count})")
        if count > 0:
            self.btn_sync_selected.configure(fg_color=PRIMARY_BLUE, hover_color=PRIMARY_HOVER)
        else:
            self.btn_sync_selected.configure(fg_color=SURFACE_LIGHTER, hover_color="#3e4249")

    def toggle_select_all(self):
        """In-place selection toggling: instant, never destroys widgets!"""
        select = self.select_all_var.get()
        if select:
            for it in self.filtered_items:
                self.selected_cids.add(it.id)
        else:
            self.selected_cids.clear()

        # Update visible checkbox variables in-place without re-rendering!
        for cid, var in self.card_checkbox_vars.items():
            var.set(select)

        # If in table view, update selection in treeview
        if self.view_mode == "table" and hasattr(self, "tree"):
            if select:
                all_ids = self.tree.get_children()
                self.tree.selection_set(all_ids)
            else:
                self.tree.selection_set([])

        self._update_selected_button()

    def sync_single_chat(self, item: ConversationItem):
        if self.is_syncing:
            return
        self._run_sync_worker([item])

    def sync_selected(self):
        if self.is_syncing or not self.selected_cids:
            return
        targets = [it for it in self.all_items if it.id in self.selected_cids]
        self._run_sync_worker(targets)

    def sync_all_pending(self):
        if self.is_syncing:
            return
        pending = [it for it in self.all_items if it.is_pending]
        if not pending:
            self.status_label.configure(
                text="All chats are already synced to Antigravity 2.0!"
            )
            return
        self._run_sync_worker(pending)

    def _run_sync_worker(self, targets: List[ConversationItem]):
        self.is_syncing = True
        self.progress_bar.set(0)
        self.btn_sync_all.configure(state="disabled")
        self.btn_sync_selected.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")

        def progress_cb(cur, total, msg):
            pct = (cur / total) if total else 1.0
            try:
                self.after(0, lambda: self._update_progress(pct, msg))
            except Exception:
                pass

        def worker():
            res = self.engine.sync_conversations(targets, on_progress=progress_cb)
            try:
                self.after(0, lambda: self._on_sync_finished(res))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, percent: float, msg: str):
        self.progress_bar.set(percent)
        self.status_label.configure(text=msg)

    def _on_sync_finished(self, result: SyncResult):
        self.is_syncing = False
        self.btn_sync_all.configure(state="normal")
        self.btn_sync_selected.configure(state="normal")
        self.btn_refresh.configure(state="normal")
        self.progress_bar.set(1.0)
        self.selected_cids.clear()
        self._update_selected_button()

        if result.is_success:
            msg = f"🎉 Successfully synced {result.total_synced} chat(s)! (Press Ctrl+R in Antigravity 2.0 to view)"
            self.status_label.configure(text=msg)
        else:
            msg = f"⚠️ Synced {result.total_synced} items, but {result.total_failed} item(s) had errors."
            self.status_label.configure(text=msg)

        # Trigger re-scan to refresh badges
        self.refresh_scan()

    def toggle_auto_sync(self):
        active = self.auto_sync_var.get()
        if active:
            if not self.watcher:
                self.watcher = ChatWatcher(
                    self.scanner,
                    self.engine,
                    interval_seconds=5.0,
                    on_sync_callback=lambda res: self.after(
                        0, lambda: self._on_auto_sync_callback(res)
                    ),
                )
            self.watcher.start()
            self.status_label.configure(
                text="Auto-Sync ENABLED: Monitoring IDE chats every 5s in background."
            )
        else:
            if self.watcher:
                self.watcher.stop()
            self.status_label.configure(text="Auto-Sync DISABLED.")

    def _on_auto_sync_callback(self, result: SyncResult):
        if result.total_synced > 0:
            now_str = time.strftime("%H:%M:%S")
            self.status_label.configure(
                text=f"[{now_str}] Auto-synced {result.total_synced} chat(s) from IDE! (Ctrl+R in 2.0 to reload)"
            )
            self.refresh_scan()

    def open_data_folder(self):
        """Open Antigravity 2.0 data directory in Windows Explorer."""
        folder = self.config.app_base
        if folder.exists():
            try:
                os.startfile(str(folder))
            except Exception:
                pass

    def show_backups_modal(self):
        """Open a popup window displaying available backups with restore option."""
        modal = ctk.CTkToplevel(self)
        modal.title("Database Backups & Rollback")
        modal.geometry("640x440")
        modal.configure(fg_color=BG_DARK)
        modal.transient(self)
        modal.grab_set()

        ctk.CTkLabel(
            modal,
            text="🛡️ Saved Database Snapshots",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(padx=20, pady=(16, 4), anchor="w")

        ctk.CTkLabel(
            modal,
            text="Automatic timestamped snapshots taken before any sync modification.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        ).pack(padx=20, pady=(0, 12), anchor="w")

        scroll = ctk.CTkScrollableFrame(modal, fg_color=SURFACE_DARK, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        backups = self.backup_mgr.list_backups()
        if not backups:
            ctk.CTkLabel(
                scroll,
                text="No backup snapshots found yet.",
                font=ctk.CTkFont(size=12),
                text_color=TEXT_MUTED,
            ).pack(pady=20)
        else:
            for b in backups:
                row = ctk.CTkFrame(scroll, fg_color=SURFACE_LIGHTER, corner_radius=6)
                row.pack(fill="x", padx=6, pady=4)

                c1 = ctk.CTkFrame(row, fg_color="transparent")
                c1.pack(side="left", padx=10, pady=8)

                ctk.CTkLabel(
                    c1,
                    text=f"{b['type']}  •  {b['timestamp']}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=TEXT_PRIMARY,
                ).pack(anchor="w")

                ctk.CTkLabel(
                    c1,
                    text=f"Size: {b['size_bytes'] / 1024:.1f} KB  |  File: {b['filename']}",
                    font=ctk.CTkFont(size=10),
                    text_color=TEXT_MUTED,
                ).pack(anchor="w")

                def make_restore_cb(path=b["path"]):
                    def do_restore():
                        ok = self.backup_mgr.restore_backup(path)
                        if ok:
                            modal.destroy()
                            self.refresh_scan()
                            self.status_label.configure(
                                text=f"Restored database from snapshot: {os.path.basename(path)}"
                            )

                    return do_restore

                btn_restore = ctk.CTkButton(
                    row,
                    text="Restore",
                    command=make_restore_cb(b["path"]),
                    font=ctk.CTkFont(size=11),
                    fg_color=PRIMARY_BLUE,
                    hover_color=PRIMARY_HOVER,
                    width=75,
                    height=26,
                )
                btn_restore.pack(side="right", padx=10)

        ctk.CTkButton(
            modal,
            text="Close",
            command=modal.destroy,
            fg_color=SURFACE_LIGHTER,
            hover_color="#3e4249",
            width=100,
        ).pack(pady=(0, 16))
