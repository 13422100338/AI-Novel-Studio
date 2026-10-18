"""Design token provider for the QML shell.

Tokens are the single source for colors, spacing, radii, durations, and fonts in
the new frontend. The old QWidget stylesheet stays untouched during migration;
convergence onto one token source is tracked as a future wiring point.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

_THEME_NAMES = ("paper", "light", "dark")
_QUALITY_NAMES = ("safe", "balanced", "premium")


def _material(theme_name: str) -> dict[str, str]:
    """Glass-material tokens per theme (ideal-UI spec 4.2/13).

    ``glassFill`` uses #AARRGGBB so QML can consume it directly; no real-time
    backdrop blur is used in the production shell (the spec forbids expensive
    blur there until Visual V4 Mica is evaluated). The ``acrylic*`` / ``glass*``
    tokens below are consumed by the standalone Visual V0 lab page only, where
    the real-time Acrylic direction is evaluated before any global adoption.

    The ``glassEdgeLight*`` / ``glassInnerShadow*`` tokens implement the
    iOS 26 "Liquid Glass" layer stack (research-backed, see AcrylicSurface.qml
    header): backdrop blur + tint + saturation/vibrancy boost + top/left edge
    light + bottom/right inner shadow + noise grain. The light source is the
    BackdropLayer background glow (``backdropGlowWarm/Cool``), not a painted
    specular sheen (removed per user feedback). Light mode is deliberately
    brighter and more saturated (matte & bright) so the material still reads
    on a light canvas; dark mode is deeper and more contrasty.
    """
    if theme_name == "paper":
        return {
            "glassFill": "#CFFBF8F0",
            "glassFillStrong": "#EBFBF8F0",
            "glassBorderHighlight": "#66FFFFFF",
            "glassBorderShadow": "#40D8D0C0",
            "paperFill": "#FFFDF7",
            "noiseOpacity": "0.025",
            # Real-time acrylic (Visual V0 lab only):
            "acrylicTint": "#FBF8F0",
            "acrylicLuminosity": "0.035",
            # Tier separation: Balanced = light blur + more solid tint,
            # Premium = strong blur + more transparent tint (visibly distinct).
            "glassBlurBalanced": "12",
            "glassBlurPremium": "56",
            "glassTintBalanced": "0.78",
            "glassTintPremium": "0.42",
            "glassTintOpacity": "0.62",
            "glassSaturation": "0.15",
            "glassBrightness": "0.03",
            "glassEdgeLightBalanced": "0.20",
            "glassEdgeLightPremium": "0.34",
            "glassInnerShadowBalanced": "0.08",
            "glassInnerShadowPremium": "0.14",
            "cardEdgeLight": "0.09",
            "cardInnerShadow": "0.04",
            # Backdrop glow strength: light mode needs noticeably richer color
            # fields so the blur+tint stack has color to transmit (iOS Liquid
            # Glass only reads over visually rich backgrounds).
            "backdropGlowWarm": "0.14",
            "backdropGlowCool": "0.12",
        }
    if theme_name == "dark":
        return {
            "glassFill": "#CC292A2D",
            "glassFillStrong": "#E8292A2D",
            "glassBorderHighlight": "#2EFFFFFF",
            "glassBorderShadow": "#3F000000",
            "paperFill": "#292A2D",
            "noiseOpacity": "0.035",
            "acrylicTint": "#292A2D",
            "acrylicLuminosity": "0.05",
            "glassBlurBalanced": "12",
            "glassBlurPremium": "56",
            "glassTintBalanced": "0.78",
            "glassTintPremium": "0.42",
            "glassTintOpacity": "0.62",
            "glassSaturation": "0.20",
            "glassBrightness": "0.08",
            "glassEdgeLightBalanced": "0.16",
            "glassEdgeLightPremium": "0.26",
            "glassInnerShadowBalanced": "0.10",
            "glassInnerShadowPremium": "0.16",
            "cardEdgeLight": "0.08",
            "cardInnerShadow": "0.05",
            "backdropGlowWarm": "0.12",
            "backdropGlowCool": "0.11",
        }
    return {
        "glassFill": "#CCFFFFFF",
        "glassFillStrong": "#EFFFFFFF",
        "glassBorderHighlight": "#66FFFFFF",
        "glassBorderShadow": "#33E4E6E8",
        "paperFill": "#FFFFFF",
        "noiseOpacity": "0.02",
        # Light-mode Liquid Glass is matte & bright but slightly cool so the
        # panel separates from the warm paper canvas instead of washing out.
        "acrylicTint": "#F5F8FB",
        "acrylicLuminosity": "0.06",
        "glassBlurBalanced": "12",
        "glassBlurPremium": "56",
        "glassTintBalanced": "0.72",
        "glassTintPremium": "0.52",
        "glassTintOpacity": "0.62",
        "glassSaturation": "0.40",
        "glassBrightness": "0.05",
        "glassEdgeLightBalanced": "0.28",
        "glassEdgeLightPremium": "0.46",
        "glassInnerShadowBalanced": "0.09",
        "glassInnerShadowPremium": "0.15",
        "cardEdgeLight": "0.10",
        "cardInnerShadow": "0.04",
        "backdropGlowWarm": "0.28",
        "backdropGlowCool": "0.24",
    }


def _elevation() -> dict[str, str]:
    return {
        "shadowSoft": "#22000000",
        "shadowStrong": "#40000000",
    }


def _motion() -> dict[str, int]:
    return {
        "micro": 100,
        "normal": 160,
        "panelFade": 140,
        "glowCycle": 2800,
    }


def _agent_colors() -> dict[str, str]:
    """AI state colors (ideal-UI spec 5.2); shared across themes."""
    return {
        "thinkingA": "#7C6FD8",
        "thinkingB": "#9B8FE8",
        "generatingA": "#7C6FD8",
        "generatingB": "#D9A85B",
        "success": "#3E7C4F",
        "error": "#A6453F",
        "waiting": "#B7791F",
        "cancelled": "#9A958C",
    }


def _palette(theme_name: str) -> dict[str, object]:
    if theme_name == "paper":
        colors = {
            "bgCanvas": "#F0E6DA",
            "bgSurface": "#FAF6F0",
            "bgSidebar": "#EFE5D8",
            "bgEditor": "#FFFAF1",
            "scrim": "#80000000",
            "textPrimary": "#3C2E25",
            "textSecondary": "#807163",
            "border": "#E0D3C3",
            "accent": "#915E31",
            "success": "#3E7C4F",
            "warning": "#B7791F",
            "danger": "#A6453F",
            "hover": "#EFE4D7",
            "pressed": "#EAD7BD",
        }
    elif theme_name == "dark":
        colors = {
            "bgCanvas": "#202124",
            "bgSurface": "#292A2D",
            "bgSidebar": "#242527",
            "bgEditor": "#292A2D",
            "scrim": "#80000000",
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
    else:  # light: clean modern palette -- bright canvas, friendly blue
        # accent (the old near-black accent read as gloomy/"阴间").
        colors = {
            "bgCanvas": "#F4F6FA",
            "bgSurface": "#FFFFFF",
            "bgSidebar": "#EDF0F5",
            "bgEditor": "#FFFFFF",
            "scrim": "#80000000",
            "textPrimary": "#1F2430",
            "textSecondary": "#5C6470",
            "border": "#E2E6EC",
            "accent": "#3A6FD8",
            "success": "#1E8E5A",
            "warning": "#C77414",
            "danger": "#D64545",
            "hover": "#E9EDF3",
            "pressed": "#DCE3EC",
        }
    return {
        "color": colors,
        "material": _material(theme_name),
        "elevation": _elevation(),
        "motion": _motion(),
        "agent": _agent_colors(),
        "spacing": {
            "xs": 4,
            "sm": 8,
            "md": 12,
            "lg": 16,
            "xl": 24,
            "xxl": 32,
        },
        "radius": {"r8": 8, "r12": 12, "r16": 16},
        "duration": {
            "fast": 120,
            "normal": 180,
            "panel": 220,
            # Content fade for one-step geometry switches (ideal-UI spec 10.1).
            "panelFade": 140,
        },
        "font": {
            "ui": "Microsoft YaHei UI",
            "manuscript": "SimSun" if theme_name == "paper" else "Microsoft YaHei",
            "mono": "Consolas",
        },
    }


def _normalize_theme_name(value: str) -> str:
    return value if value in _THEME_NAMES else "paper"


def _normalize_quality_name(value: str) -> str:
    return value if value in _QUALITY_NAMES else "balanced"


class ThemeProvider(QObject):
    """Exposes the current token map to QML as the ``Theme`` singleton."""

    tokens_changed = Signal()
    quality_changed = Signal()

    def __init__(self, theme_name: str = "paper", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._theme_name = _normalize_theme_name(theme_name)
        self._visual_quality = "balanced"
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

    @Property(str, notify=quality_changed)
    def visualQuality(self) -> str:
        return self._visual_quality

    @Slot(str)
    def setVisualQuality(self, quality: str) -> None:
        name = _normalize_quality_name(quality)
        if name == self._visual_quality:
            return
        self._visual_quality = name
        self.quality_changed.emit()

    @Slot(result=str)
    def nextVisualQuality(self) -> str:
        index = _QUALITY_NAMES.index(self._visual_quality)
        return _QUALITY_NAMES[(index + 1) % len(_QUALITY_NAMES)]
