from PySide6.QtCore import QObject

from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider


def test_default_theme_is_paper() -> None:
    theme = ThemeProvider()
    assert theme.property("themeName") == "paper"
    tokens = theme.property("tokens")
    assert tokens["color"]["bgCanvas"] == "#F0E6DA"
    assert tokens["spacing"]["lg"] == 16
    assert tokens["radius"]["r16"] == 16
    assert tokens["duration"]["panel"] == 220
    assert tokens["duration"]["panelFade"] == 140
    assert tokens["color"]["scrim"] == "#80000000"
    material = tokens["material"]
    assert material["glassBlurBalanced"] == "12"
    assert material["glassBlurPremium"] == "56"
    assert material["glassTintBalanced"] == "0.78"
    assert material["glassTintPremium"] == "0.42"
    assert material["glassTintOpacity"] == "0.62"
    assert material["acrylicTint"] == "#FBF8F0"


def test_set_theme_valid_and_invalid() -> None:
    theme = ThemeProvider()
    theme.setTheme("dark")
    assert theme.property("themeName") == "dark"
    assert theme.property("tokens")["color"]["bgCanvas"] == "#202124"
    assert theme.property("tokens")["material"]["acrylicTint"] == "#292A2D"
    theme.setTheme("unknown")
    assert theme.property("themeName") == "paper"


def test_next_theme_cycles() -> None:
    theme = ThemeProvider("dark")
    assert theme.nextThemeName() == "paper"
    theme.setTheme("light")
    assert theme.nextThemeName() == "dark"
    theme.setTheme("paper")
    assert theme.nextThemeName() == "light"


def test_theme_provider_is_qobject() -> None:
    assert isinstance(ThemeProvider(), QObject)


def test_liquid_glass_tokens_per_theme_and_tier() -> None:
    """Edge light/inner shadow tokens: premium > balanced in every theme. The
    diagonal specular sheen was removed per user feedback (the light source is
    the backdrop glow), so its tokens must not silently return."""
    theme = ThemeProvider()
    for name in ("paper", "light", "dark"):
        theme.setTheme(name)
        material = theme.property("tokens")["material"]
        assert "glassSpecularPremium" not in material, f"{name}: sheen returned"
        assert "glassSpecularBalanced" not in material, f"{name}: sheen returned"
        assert float(material["glassEdgeLightPremium"]) > float(
            material["glassEdgeLightBalanced"]
        ), f"{name}: edge light premium must be stronger"
        assert float(material["glassInnerShadowPremium"]) > float(
            material["glassInnerShadowBalanced"]
        ), f"{name}: inner shadow premium must be stronger"
        assert float(material["cardEdgeLight"]) > 0
        assert float(material["cardInnerShadow"]) > 0
        # Flat-style guardrail (user feedback: shadows should be faint, style
        # flatter): inner shadows stay well under the old values everywhere.
        assert float(material["cardInnerShadow"]) <= 0.06
        assert float(material["glassInnerShadowPremium"]) <= 0.20

    # Light theme must be visibly brighter/more saturated than dark.
    theme.setTheme("light")
    light = theme.property("tokens")["material"]
    theme.setTheme("dark")
    dark = theme.property("tokens")["material"]
    assert float(light["glassSaturation"]) > float(dark["glassSaturation"])
    assert float(light["glassEdgeLightPremium"]) > float(dark["glassEdgeLightPremium"])
    assert float(light["glassSaturation"]) > 0
    # Light mode gets richer backdrop glows so the glass has color to transmit.
    assert float(light["backdropGlowWarm"]) > float(dark["backdropGlowWarm"])
    assert float(light["backdropGlowCool"]) > float(dark["backdropGlowCool"])
