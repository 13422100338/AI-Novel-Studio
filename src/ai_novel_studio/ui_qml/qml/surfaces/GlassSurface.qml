import QtQuick
import "../effects"

// Simulated glass (ideal-UI spec 4.2): translucent fill + top inner highlight
// + hairline border with a deeper bottom edge + static noise + soft shadow.
// Deliberately no real-time backdrop blur — the spec forbids expensive blur
// in the shell until Visual V4.
Item {
    id: root

    default property alias content: contentArea.data

    property real radius: Theme.tokens.radius.r12
    property bool elevated: true
    // Opaque glass mode (Visual V0 lab, Mica backdrop): solid fill that never
    // lets the wallpaper through, while keeping the glass decorations (top
    // inner highlight, hairline border, noise). The production shell does not
    // use this property yet.
    property bool opaque: false
    // Test/behavior hook: expose the effective fill color so QML tests can
    // assert Safe tier degrades to an opaque surface.
    readonly property color fillColor: fill.color

    // Soft static shadow behind the pane (Safe tier may keep static shadows).
    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 2
        radius: root.radius + 2
        color: "transparent"
        border.width: root.elevated ? 5 : 3
        border.color: Theme.tokens.elevation.shadowSoft
        z: -1
    }

    Rectangle {
        id: fill
        anchors.fill: parent
        radius: root.radius
        // Safe tier degrades to an opaque surface; Balanced/Premium use glass.
        color: Theme.visualQuality === "safe"
            ? Theme.tokens.color.bgSurface
            : root.opaque
                ? Theme.tokens.color.bgSurface
                : Theme.tokens.material.glassFill
        border.color: Theme.tokens.color.border
        border.width: 1

        // Top inner highlight: the light catching the material.
        Rectangle {
            visible: root.opaque || Theme.visualQuality !== "safe"
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.topMargin: 1
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            height: 1
            color: Theme.tokens.material.glassBorderHighlight
            radius: 1
        }
        // Deeper bottom edge reads as the material's thickness.
        Rectangle {
            visible: root.opaque || Theme.visualQuality !== "safe"
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottomMargin: 0
            height: 1
            color: Theme.tokens.material.glassBorderShadow
        }

        NoiseOverlay {
            anchors.fill: parent
            anchors.margins: 1
        }

        Item {
            id: contentArea
            anchors.fill: parent
        }
    }
}
