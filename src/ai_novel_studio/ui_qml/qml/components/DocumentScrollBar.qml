import QtQuick
import QtQuick.Controls.Basic

ScrollBar {
    id: root
    implicitWidth: 14
    orientation: Qt.Vertical
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.right: parent.right
    padding: 3
    minimumSize: 0.08
    policy: ScrollBar.AlwaysOn
    interactive: true
    active: hovered || pressed
    z: 2
    background: Rectangle {
        color: Theme.tokens.color.hover
        radius: 7
    }
    contentItem: Rectangle {
        implicitWidth: 8
        radius: 4
        color: root.pressed ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
        opacity: root.active ? 0.95 : 0.6
    }
}
