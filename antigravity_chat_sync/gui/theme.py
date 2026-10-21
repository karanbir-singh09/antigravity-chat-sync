"""Theme and color palette for Antigravity Chat Sync GUI.
Matches Google Antigravity dark styling.
"""

# Color Palette
BG_DARK = "#18191c"
SURFACE_DARK = "#232529"
SURFACE_LIGHTER = "#2e3136"
BORDER_COLOR = "#383b42"

PRIMARY_BLUE = "#3b82f6"
PRIMARY_HOVER = "#2563eb"

SUCCESS_GREEN = "#10b981"
SUCCESS_BG = "#064e3b"

WARNING_AMBER = "#f59e0b"
WARNING_BG = "#78350f"

INFO_CYAN = "#06b6d4"

TEXT_PRIMARY = "#f9fafb"
TEXT_SECONDARY = "#9ca3af"
TEXT_MUTED = "#6b7280"

# Status Badges
STATUS_COLORS = {
    "NEW": {"fg": SUCCESS_GREEN, "bg": SUCCESS_BG, "label": "NEW IN IDE"},
    "UPDATED": {"fg": WARNING_AMBER, "bg": WARNING_BG, "label": "UPDATED"},
    "SYNCED": {"fg": TEXT_SECONDARY, "bg": SURFACE_LIGHTER, "label": "SYNCED"},
}
