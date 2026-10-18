import QtQuick
import "../effects"

// Opaque surface with a restrained static shadow (Safe tier allows static
// shadows; no blur, no shader). Two soft layers approximate elevation.
Item {
    id: root

    default property alias content: contentArea.data

    property real radius: Theme.tokens.radius.r12
    property real elevation: 2

    Rectangle {
        anchors.fill: parent
        anchors.margins: 0
        radius: root.radius + 2
        color: "transparent"
        border.width: Math.max(2, Math.round(root.elevation))
        border.color: Theme.tokens.elevation.shadowSoft
        z: -1
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        color: Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        border.width: 1
        radius: root.radius

        Item {
            id: contentArea
            anchors.fill: parent
        }
    }
}
