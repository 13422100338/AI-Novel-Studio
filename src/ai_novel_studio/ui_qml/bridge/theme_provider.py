"""Design token provider for the QML shell.

Tokens are the single source for colors, spacing, radii, durations, and fonts in
the new frontend. The old QWidget stylesheet stays untouched during migration;
convergence onto one token source is tracked as a future wiring point.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

_THEME_NAMES = ("paper", "light", "dark")


def _palette(theme_name: str) -> dict[str, object]:
    if theme_name == "paper":
        colors = {
            "bgCanvas": "#F3EFE6",
            "bgSurface": "#FBF8F0",
            "bgSidebar": "#EDE7DA",
            "bgEditor": "#FFFDF7",
            "textPrimary": "#2B2925",
            "textSecondary": "#6E6A61",
            "border": "#D8D0C0",
            "accent": "#8C5A2B",
            "success": "#3E7C4F",
            "warning": "#B7791F",
            "danger": "#A6453F",
            "hover": "#E8E1D2",
            "pressed": "#DDD4C2",
        }
    elif theme_name == "dark":
        colors = {
            "bgCanvas": "#202124",
            "bgSurface": "#292A2D",
            "bgSidebar": "#242527",
            "bgEditor": "#292A2D",
            "textPrimary": "#E8EAED",
            "textSecondary": "#AEB2B7",
            "border": "#3C4043",
            "accent": "#8AB4F8",
            "success": "#81C995",
            "warning": "#FDD663",
            "danger": "#F28B82",
            "hover": "#3C4043",
            "pressed": "#484B4F",
        }
    else:  # light editor palette mirrors the current QWidget light theme
        colors = {
            "bgCanvas": "#F6F7F8",
            "bgSurface": "#FFFFFF",
            "bgSidebar": "#EEF0F2",
            "bgEditor": "#FFFFFF",
            "textPrimary": "#202124",
            "textSecondary": "#6F7378",
            "border": "#E4E6E8",
            "accent": "#242629",
            "success": "#1E7A46",
            "warning": "#B7791F",
            "danger": "#C0392B",
            "hover": "#E9EAEC",
            "pressed": "#DFE1E3",
        }
    return {
        "color": colors,
        "spacing": {
            "xs": 4,
            "sm": 8,
            "md": 12,
            "lg": 16,
            "xl": 24,
            "xxl": 32,
        },
        "radius": {"r8": 8, "r12": 12, "r16": 16},
        "duration": {"fast": 120, "normal": 180, "panel": 220},
        "font": {
            "ui": "Microsoft YaHei UI",
            "manuscript": "Microsoft YaHei",
            "mono": "Consolas",
        },
    }


def _normalize_theme_name(value: str) -> str:
    return value if value in _THEME_NAMES else "paper"


class ThemeProvider(QObject):
    """Exposes the current token map to QML as the ``Theme`` singleton."""

    tokens_changed = Signal()

    def __init__(self, theme_name: str = "paper", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._theme_name = _normalize_theme_name(theme_name)
        self._tokens = _palette(self._theme_name)

    @Property(str, notify=tokens_changed)
    def themeName(self) -> str:
        return self._theme_name

    @Property("QVariantMap", notify=tokens_changed)  # type: ignore[arg-type]
    def tokens(self) -> dict[str, object]:
        return self._tokens

    @Slot(str)
    def setTheme(self, theme_name: str) -> None:
        name = _normalize_theme_name(theme_name)
        if name == self._theme_name:
            return
        self._theme_name = name
        self._tokens = _palette(name)
        self.tokens_changed.emit()

    @Slot(result=str)
    def nextThemeName(self) -> str:
        index = _THEME_NAMES.index(self._theme_name)
        return _THEME_NAMES[(index + 1) % len(_THEME_NAMES)]
