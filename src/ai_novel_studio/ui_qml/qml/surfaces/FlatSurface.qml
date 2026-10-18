import QtQuick
import "../effects"

// Opaque, bordered surface (Safe tier). The base for GlassSurface and
// ElevatedSurface; all materials derive from Theme tokens only.
Rectangle {
    id: root

    default property alias content: contentArea.data

    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1
    radius: root.radius

    Item {
        id: contentArea
        anchors.fill: parent
    }
}
