import QtQuick
import "../effects"

// App-controlled backdrop layer (glass-UI course correction, doc:
// 2026-08-04-glass-ui-course-correction.md). This is the RECOMMENDED main
// route for the glass direction: an opaque Qt window whose background is a
// controlled, theme-aware layer that the Acrylic surfaces above blur.
//
// Responsibilities:
// - warm theme gradient (paper / light / dark);
// - low-contrast cool/warm color fields;
// - very light notebook hairlines + optional literary sample cards
//   (background complexity so real blur reads as glass);
// - optional "wash" sub-layer for the Mica experiment (system backdrop is an
//   optional experiment, never a required visual source);
// - never contains the panels/cards that sit on top of it, so the
//   ShaderEffectSource can never capture itself.
Item {
    id: root

    // Mica experiment wash: semi-transparent themed layer over the DWM
    // wallpaper blur for readability. Enabled only by the lab page when the
    // system backdrop is active (optional experiment; frozen by default).
    property bool washEnabled: false
    property real washAlpha: 0.32

    // Helper: theme color with a low alpha (background decorations only).
    // Typed `color` parameter is required: Theme.tokens.* values are strings
    // ("#RRGGBB"); an untyped parameter leaves color.r/g/b undefined and
    // Qt.rgba() silently produces black.
    function tint(color: color, alpha: real): color {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    // Mica wash (system-backdrop experiment only).
    Item {
        anchors.fill: parent
        visible: root.washEnabled

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: root.tint(Theme.tokens.color.bgCanvas, root.washAlpha)
                }
                GradientStop {
                    position: 0.55
                    color: root.tint(Theme.tokens.color.bgCanvas, root.washAlpha - 0.10)
                }
                GradientStop {
                    position: 1.0
                    color: root.tint(Theme.tokens.color.bgCanvas, root.washAlpha - 0.06)
                }
            }
        }
        NoiseOverlay {
            anchors.fill: parent
        }
    }

    // --- Decorative content (in-app backdrop). Hidden when the Mica wash is
    // active so the wallpaper blur is the only material behind the panels.
    Rectangle {
        anchors.fill: parent
        visible: !root.washEnabled
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: root.tint(Theme.tokens.color.bgCanvas, 1)
            }
            GradientStop {
                position: 0.6
                color: root.tint(Qt.lighter(Theme.tokens.color.bgCanvas, 1.04), 1)
            }
            GradientStop {
                position: 1.0
                color: root.tint(Theme.tokens.color.bgCanvas, 1)
            }
        }
    }

    // Notebook hairlines give the blur something fine to smear.
    Repeater {
        model: 4
        visible: !root.washEnabled
        Rectangle {
            x: parent.width * (0.16 + index * 0.22)
            y: parent.height * 0.10
            width: 1
            height: parent.height * 0.76
            color: Theme.tokens.color.border
            opacity: 0.30
        }
    }

    // --- Light fields (diagnosis doc §6.3): recognizable but low-contrast
    // warm/cool glows + faint geometry so the Acrylic blur has something to
    // soften. Colors come only from Theme tokens (low alpha, calm).

    // Top-left warm gold glow (behind the nav/sidebar area).
    Rectangle {
        visible: !root.washEnabled
        x: -parent.width * 0.06
        y: -parent.height * 0.06
        width: parent.width * 0.42
        height: parent.height * 0.44
        radius: parent.width * 0.21
        color: root.tint(
            Theme.tokens.color.warning,
            parseFloat(Theme.tokens.material.backdropGlowWarm)
        )
    }

    // Top-right cool blue-violet glow (behind the AI panel).
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.64
        y: -parent.height * 0.05
        width: parent.width * 0.42
        height: parent.height * 0.46
        radius: parent.width * 0.21
        color: root.tint(
            Theme.tokens.agent.thinkingA,
            parseFloat(Theme.tokens.material.backdropGlowCool)
        )
    }

    // Mid-lower gray-blue soft light (behind the paper bottom).
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.28
        y: parent.height * 0.58
        width: parent.width * 0.44
        height: parent.height * 0.34
        radius: parent.width * 0.22
        color: root.tint(Theme.tokens.color.textSecondary, 0.05)
    }

    // Faint geometry outlines: ring + diagonal hairline (barely visible).
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.40
        y: parent.height * 0.26
        width: parent.width * 0.10
        height: parent.width * 0.10
        radius: parent.width * 0.05
        color: "transparent"
        border.color: Theme.tokens.color.border
        border.width: 1
        opacity: 0.45
    }
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.20
        y: parent.height * 0.66
        width: parent.width * 0.055
        height: 1
        rotation: -24
        color: Theme.tokens.color.border
        opacity: 0.35
    }

    // Recognizable manuscript block behind the AI panel (right side): this is
    // what makes the tier blur difference visible. Balanced (blur 12) keeps a
    // soft but legible edge; Premium (blur 56) smears it into a color field.
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.76
        y: parent.height * 0.24
        width: parent.width * 0.20
        height: parent.height * 0.24
        radius: 14
        color: Theme.tokens.material.paperFill
        opacity: 0.82
        border.color: Theme.tokens.color.border
        border.width: 1

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 5
            Text {
                width: parent.width
                text: "第三章 灯塔"
                font.pixelSize: 10
                font.bold: true
                color: root.tint(Theme.tokens.color.textPrimary, 0.6)
            }
            Text {
                width: parent.width
                text: "雾从海面漫上来，灯塔的光在雾气里变得又厚又软，像一团被揉过的暖色。"
                font.pixelSize: 9
                lineHeight: 1.5
                wrapMode: Text.WordWrap
                color: root.tint(Theme.tokens.color.textSecondary, 0.65)
            }
            Text {
                width: parent.width
                text: "他数着灯旋转的间隔，一圈、两圈，直到栈桥尽头的渔火也亮了起来。"
                font.pixelSize: 9
                lineHeight: 1.5
                wrapMode: Text.WordWrap
                color: root.tint(Theme.tokens.color.textSecondary, 0.65)
            }
        }
    }

    // Warm accent chip behind the AI panel bottom: gives the blur a colored
    // edge to soften, making Premium visibly different from Balanced.
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.80
        y: parent.height * 0.72
        width: parent.width * 0.13
        height: parent.width * 0.13
        radius: parent.width * 0.065
        color: root.tint(Theme.tokens.color.accent, 0.16)
    }

    // Manuscript excerpt card (behind the AI glass column).
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.035
        y: parent.height * 0.52
        width: parent.width * 0.26
        height: parent.height * 0.26
        radius: 14
        color: Theme.tokens.material.paperFill
        opacity: 0.85
        border.color: Theme.tokens.color.border
        border.width: 1

        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 6
            Text {
                width: parent.width
                text: "第六章 渡口"
                font.pixelSize: 11
                font.bold: true
                color: root.tint(Theme.tokens.color.textPrimary, 0.55)
            }
            Text {
                width: parent.width
                text: "渡轮靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。"
                font.pixelSize: 10
                lineHeight: 1.6
                wrapMode: Text.WordWrap
                color: root.tint(Theme.tokens.color.textSecondary, 0.6)
            }
            Text {
                width: parent.width
                text: "林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。"
                font.pixelSize: 10
                lineHeight: 1.6
                wrapMode: Text.WordWrap
                color: root.tint(Theme.tokens.color.textSecondary, 0.6)
            }
        }
    }

    // Outline card (behind the Agent card column).
    Rectangle {
        visible: !root.washEnabled
        x: parent.width * 0.69
        y: parent.height * 0.72
        width: parent.width * 0.27
        height: parent.height * 0.22
        radius: 14
        color: Theme.tokens.color.bgSurface
        opacity: 0.9
        border.color: Theme.tokens.color.border
        border.width: 1

        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 5
            Text {
                width: parent.width
                text: "大纲 · 第二卷"
                font.pixelSize: 11
                font.bold: true
                color: root.tint(Theme.tokens.color.textPrimary, 0.55)
            }
            Text {
                width: parent.width
                text: "· 人物：林默（退役水手）"
                font.pixelSize: 10
                color: root.tint(Theme.tokens.color.textSecondary, 0.6)
            }
            Text {
                width: parent.width
                text: "· 地点：雾港 · 老渡口"
                font.pixelSize: 10
                color: root.tint(Theme.tokens.color.textSecondary, 0.6)
            }
        }
    }
}
