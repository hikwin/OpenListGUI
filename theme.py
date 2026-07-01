# -*- coding: utf-8 -*-
"""
Theme Configurations for the OpenList GUI Manager.
Defines colors, fonts, and styling tokens using a premium slate/dark theme.
"""

# ==============================================================================
# Color Palette (Slate Dark Theme / Catppuccin inspired)
# ==============================================================================
BG_MAIN = "#0f172a"          # Deep dark slate background
BG_SIDEBAR = "#1e293b"       # Slightly lighter slate for sidebar
BG_CARD = "#1e293b"          # Card background
BG_CARD_HOVER = "#334155"    # Card hover background
BG_CONSOLE = "#020617"       # Very dark slate for terminal console

# Foreground & Text Colors
COLOR_TEXT_MAIN = "#f8fafc"  # Crisp white/slate for primary text
COLOR_TEXT_MUTED = "#94a3b8" # Muted gray-blue for secondary text
COLOR_TEXT_CONSOLE = "#cbd5e1"# Light gray for console logs

# Accent & State Colors
COLOR_ACCENT = "#38bdf8"      # Bright sky blue for primary buttons/accents
COLOR_ACCENT_HOVER = "#0ea5e9"# Darker blue for hover states
COLOR_SUCCESS = "#10b981"     # Emerald green for "Running" or "Success"
COLOR_ERROR = "#ef4444"       # Rose red for "Stopped" or "Error"
COLOR_WARNING = "#f59e0b"     # Amber yellow for warnings or busy states

# ==============================================================================
# Typography
# ==============================================================================
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

FONT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_HEADER = (FONT_FAMILY, 14, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 12, "bold")
FONT_BODY = (FONT_FAMILY, 11)
FONT_MUTED = (FONT_FAMILY, 10)
FONT_CONSOLE = (FONT_MONO, 10)
