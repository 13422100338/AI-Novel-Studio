import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// WebEngine-mode AI reference drawer: a true layout cell inside the central
// RowLayout. Opening it shrinks the editor; it never overlays the WebEngine
// native surface. Content is the plot-discussion chat panel.
Rectangle {
    id: root
    objectName: "dockedAiDrawer"

    property bool open: false
    property int preferredWidth: 340
    property bool fillHeight: true
    signal closed()

    visible: root.open
    Layout.preferredWidth: root.preferredWidth
    Layout.fillHeight: root.fillHeight
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1
    clip: true

    DiscussionPanel {
        anchors.fill: parent
    }

    AppButton {
        objectName: "dockedDrawerCloseButton"
        text: "关闭"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 8
        z: 2
        onClicked: root.closed()
    }
}
