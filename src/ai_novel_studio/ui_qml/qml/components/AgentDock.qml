import QtQuick
import QtQuick.Layouts
import "../surfaces"

// Resizable, docked AI Assistant panel. It is a layout cell (never overlays the
// WebEngine surface). Drag the left edge to resize, double-click to restore,
// collapse to a slim expand tab.
//
// Geometry switches are always one-step (ideal-UI spec 10.1): an animated
// Layout.preferredWidth resizes the WebEngineView frame by frame and repaints
// black edge strips, so opening/closing snaps and the content fades in/out.
// Dragging shows a preview line and commits the width on release instead of
// resizing the layout every mouse move.
Item {
    id: root
    objectName: "agentDock"

    property bool open: false
    property int collapsedWidth: 34
    property int defaultWidth: 380
    property int minWidth: 320
    property int maxWidth: Math.max(320, Math.round(windowWidth * 0.45))
    property int windowWidth: 1440
    property int currentWidth: defaultWidth
    property bool reduceMotion: Facade.reduceMotion
    property bool dragging: false
    // Production-shell glass integration: window BackdropLayer (same source as
    // the other columns). When null the panel keeps its original opaque fill,
    // so standalone harnesses and non-shell uses are unaffected.
    property Item backdropSource: null
    // BlockHelm-style native glass: use a lighter translucent tint so the DWM
    // material behind the window shows through (no in-app blur here).
    property bool nativeGlassActive: false
    // Test/drag-state hook: MouseArea copies the pointer position here and the
    // no-argument functions below run the actual drag state machine.
    property real dragPointerX: 0
    property real dragStartX: 0
    property bool dragMoved: false
    property real dragPreviewX: 0
    signal closed()

    // UI state always follows the facade; QML never assigns `open` directly.
    Layout.preferredWidth: root.open ? root.currentWidth : root.collapsedWidth
    Layout.fillHeight: true
    Layout.minimumWidth: root.open ? root.minWidth : root.collapsedWidth
    Layout.maximumWidth: root.maxWidth
    clip: true

    Rectangle {
        id: panelSurface
        anchors.fill: parent
        // Flat shell: opaque theme surface. The translucent tint only remains
        // for the BlockHelm-style native-glass experiment (DWM material
        // behind the window must show through).
        color: root.nativeGlassActive
            ? Theme.tokens.nativeGlass.sidebarTint
            : Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        border.width: 1
        radius: 16
        opacity: 0
        scale: 0.97
        visible: false
        enabled: root.open
        // The dock lives at the window's right edge: content arrives from and
        // exits toward that edge (spatial consistency, apple-design §7).
        transformOrigin: Qt.RightEdge

        CreativeAgentPanel {
            anchors.fill: parent
        }

        // Edge-light/inner-shadow overlay belongs to the glass language; the
        // flat shell keeps plain opaque panels (native-glass experiment only).
        LiquidLights {
            objectName: "agentDockLiquidLights"
            anchors.fill: parent
            radius: 0
            visible: root.nativeGlassActive
            edgeLightOpacity: parseFloat(Theme.tokens.material.cardEdgeLight)
            innerShadowOpacity: parseFloat(Theme.tokens.material.cardInnerShadow)
        }

        ParallelAnimation {
            id: panelFadeIn
            NumberAnimation {
                target: panelSurface
                property: "opacity"
                to: 1
                duration: root.reduceMotion ? 0 : Theme.tokens.duration.panelFade
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: panelSurface
                property: "scale"
                to: 1
                duration: root.reduceMotion ? 0 : Theme.tokens.duration.panelFade
                easing.type: Easing.OutCubic
            }
        }
        ParallelAnimation {
            id: panelFadeOut
            NumberAnimation {
                target: panelSurface
                property: "opacity"
                to: 0
                // Exits snap faster than enters (asymmetric timing, emil-design-eng).
                duration: root.reduceMotion ? 0 : Theme.tokens.duration.fast
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: panelSurface
                property: "scale"
                to: 0.97
                duration: root.reduceMotion ? 0 : Theme.tokens.duration.fast
                easing.type: Easing.OutCubic
            }
            onFinished: panelSurface.visible = false
        }

        function setOpen(open) {
            if (open) {
                panelFadeOut.stop()
                panelSurface.visible = true
                panelSurface.opacity = 0
                panelSurface.scale = 0.97
                panelFadeIn.start()
            } else {
                panelFadeIn.stop()
                panelFadeOut.start()
            }
        }

        Component.onCompleted: panelSurface.setOpen(root.open)

        Connections {
            target: root
            function onOpenChanged() {
                panelSurface.setOpen(root.open)
            }
        }
    }

    Rectangle {
        id: handle
        objectName: "agentResizeHandle"
        width: 3
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        visible: root.open
        color: "transparent"

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeHorCursor
            onPressed: {
                root.dragPointerX = mouse.x
                root.beginResizeDrag()
            }
            onPositionChanged: {
                root.dragPointerX = mouse.x
                root.updateResizeDrag()
            }
            onReleased: {
                root.dragPointerX = mouse.x
                root.commitResizeDrag()
            }
            onCanceled: root.cancelResizeDrag()
            onDoubleClicked: root.resetWidth()
        }
    }

    // Width preview line: the dock keeps its current geometry while dragging
    // and commits exactly once on release (ideal-UI spec 10.1).
    Rectangle {
        id: dragPreview
        objectName: "agentDragPreview"
        width: 2
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        x: root.dragPreviewX - 1
        visible: root.dragging
        color: Theme.tokens.color.accent
    }

    // Collapsed expand tab
    Rectangle {
        id: expandTab
        objectName: "agentExpandTab"
        width: 34
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        visible: !root.open
        color: Theme.tokens.color.bgSidebar
        border.color: Theme.tokens.color.border
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: "AI 助手"
            font.pixelSize: 10
            rotation: 90
            color: Theme.tokens.color.textSecondary
        }
        MouseArea {
            anchors.fill: parent
            onClicked: root.openFromTab()
        }
    }

    function openFromTab() {
        // Restore the default width first so reopening is predictable.
        root.currentWidth = root.defaultWidth
        Facade.toggleAiDrawer(true)
    }

    function resetWidth() {
        root.currentWidth = root.defaultWidth
    }

    function clampWidth(value) {
        return Math.max(
            root.minWidth,
            Math.min(root.maxWidth, Math.round(value))
        )
    }

    function beginResizeDrag() {
        root.dragging = true
        root.dragMoved = false
        root.dragStartX = root.dragPointerX
        root.dragPreviewX = Math.max(0, Math.min(root.width, root.dragPointerX))
    }

    function updateResizeDrag() {
        if (!root.dragging) {
            return
        }
        root.dragMoved = root.dragMoved ||
            Math.abs(root.dragPointerX - root.dragStartX) > 3
        root.dragPreviewX = Math.max(0, Math.min(root.width, root.dragPointerX))
    }

    function commitResizeDrag() {
        if (!root.dragging) {
            return
        }
        root.dragging = false
        if (!root.dragMoved) {
            // A simple click on the handle must not shrink the panel.
            return
        }
        root.currentWidth = root.clampWidth(root.width - root.dragPointerX)
    }

    function cancelResizeDrag() {
        root.dragging = false
    }
}
