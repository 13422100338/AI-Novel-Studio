import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../surfaces"

// Experiment controls for the Visual V0 rework (diagnosis doc §10).
// This is a top fold-down control strip (the "折叠区域" option): when open,
// the main four-column workspace shifts down instead of being covered, so the
// AI panel is never hidden behind the controls. Escape or the "关闭" button
// closes it; the previous right-side drawer covered the AI panel and its
// full-screen dim made it look "stacked" and hard to dismiss.
Item {
    id: root
    objectName: "experimentControlPanel"

    property bool open: false
    property bool debugBackdrop: false
    property bool debugSourceRect: false
    property bool debugBlurRegion: false
    property bool micaExperiment: false
    property string micaStatus: "未启用"
    property real fpsEstimate: 0
    property string renderBackend: "unknown"
    signal closed()
    signal micaChanged(bool enabled)
    signal debugBackdropToggled(bool enabled)
    signal debugSourceRectToggled(bool enabled)
    signal debugBlurRegionToggled(bool enabled)

    implicitHeight: body.implicitHeight + 24

    function requestMica(enable: bool) {
        var ok = false
        if (enable) {
            ok = BackdropBridge.apply("mica")
        } else {
            BackdropBridge.apply("none")
        }
        root.micaStatus = enable
            ? (ok ? "Mica 已启用（真机确认）" : "不可用（本机不支持/离屏）")
            : "未启用"
        // Only switch the window to transparent when DWM actually accepted
        // the backdrop. On failure the window must stay opaque (no black
        // bare regions) and the toggle snaps back to off.
        if (ok) {
            root.micaExperiment = true
            root.micaChanged(true)
        } else {
            root.micaExperiment = false
            root.micaChanged(false)
        }
        return ok
    }

    // Escape closes the strip when it has focus.
    focus: root.open
    Keys.onEscapePressed: root.closed()

    Rectangle {
        anchors.fill: parent
        color: Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        border.width: 1
        radius: Theme.tokens.radius.r12

        // Unified edge language with the glass panels/cards (edge light +
        // inner shadow, no specular). The control strip stays effectively
        // opaque for readability; only the rim matches the material system.
        LiquidLights {
            objectName: "controlPanelLiquidLights"
            anchors.fill: parent
            radius: Theme.tokens.radius.r12
            edgeLightOpacity: parseFloat(Theme.tokens.material.cardEdgeLight)
            innerShadowOpacity: parseFloat(Theme.tokens.material.cardInnerShadow)
        }
    }

    ColumnLayout {
        id: body
        anchors.fill: parent
        anchors.margins: 12
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "实验控制"
                font.pixelSize: 13
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "experimentCloseButton"
                text: "关闭（Esc）"
                ghost: true
                onClicked: root.closed()
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8

            // Theme.
            RowLayout {
                spacing: 4
                Text {
                    text: "主题"
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }
                Repeater {
                    model: ["paper", "light", "dark"]
                    AppButton {
                        objectName: "labTheme-" + modelData
                        text: modelData
                        selected: Theme.themeName === modelData
                        onClicked: Theme.setTheme(modelData)
                    }
                }
            }

            // Quality.
            RowLayout {
                spacing: 4
                Text {
                    text: "质量"
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }
                Repeater {
                    model: ["safe", "balanced", "premium"]
                    AppButton {
                        objectName: "labQuality-" + modelData
                        text: modelData
                        primary: Theme.visualQuality === modelData
                        onClicked: Theme.setVisualQuality(modelData)
                    }
                }
            }

            // Motion.
            AppButton {
                objectName: "labReduceMotionButton"
                text: Facade.reduceMotion ? "动效：关" : "动效：开"
                ghost: true
                onClicked: Facade.setReduceMotion(!Facade.reduceMotion)
            }

            // Mica (optional experiment, default off).
            AppButton {
                objectName: "labMicaToggle"
                text: root.micaExperiment ? "Mica：开" : "Mica：关（默认）"
                primary: root.micaExperiment
                onClicked: root.requestMica(!root.micaExperiment)
            }
            Text {
                text: root.micaStatus
                font.pixelSize: 10
                verticalAlignment: Text.AlignVCenter
                color: Theme.tokens.color.textSecondary
            }

            // Debug overlays.
            AppButton {
                objectName: "labDebugBackdropToggle"
                text: root.debugBackdrop ? "背景原图：显示" : "背景原图：隐藏"
                ghost: true
                onClicked: {
                    root.debugBackdrop = !root.debugBackdrop
                    root.debugBackdropToggled(root.debugBackdrop)
                }
            }
            AppButton {
                objectName: "labDebugSourceRectToggle"
                text: root.debugSourceRect ? "sourceRect：显示" : "sourceRect：隐藏"
                ghost: true
                onClicked: {
                    root.debugSourceRect = !root.debugSourceRect
                    root.debugSourceRectToggled(root.debugSourceRect)
                }
            }
            AppButton {
                objectName: "labDebugBlurRegionToggle"
                text: root.debugBlurRegion ? "blur 区域：显示" : "blur 区域：隐藏"
                ghost: true
                onClicked: {
                    root.debugBlurRegion = !root.debugBlurRegion
                    root.debugBlurRegionToggled(root.debugBlurRegion)
                }
            }

            // Performance info (diagnosis doc §10): FPS + render backend.
            Text {
                text: "FPS：" + root.fpsEstimate.toFixed(0) + " · 后端：" + root.renderBackend
                font.pixelSize: 10
                verticalAlignment: Text.AlignVCenter
                color: Theme.tokens.color.textSecondary
            }
        }
    }
}
