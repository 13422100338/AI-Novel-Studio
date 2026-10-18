import QtQuick
import "../effects"

// The manuscript "paper" (ideal-UI spec 4.2): warm-white, opaque, very light
// texture, low-contrast border, soft static shadow. Never translucent and
// never blurred so the author's text stays perfectly stable to read.
Item {
    id: root

    default property alias content: contentArea.data

    property real radius: Theme.tokens.radius.r8
    property bool elevated: true

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 2
        radius: root.radius + 1
        color: "transparent"
        border.width: root.elevated ? 4 : 2
        border.color: Theme.tokens.elevation.shadowSoft
        z: -1
    }

    Rectangle {
        id: paper
        anchors.fill: parent
        color: Theme.tokens.material.paperFill
        radius: root.radius
        border.color: Theme.tokens.color.border
        border.width: 1

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
