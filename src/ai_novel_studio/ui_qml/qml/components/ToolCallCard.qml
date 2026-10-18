import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "toolCallCard"

    property string label: ""
    property string text: ""
    property bool busy: false
    property string status: ""

    width: parent ? parent.width : 320
    implicitHeight: Math.max(30, row.implicitHeight + 12)
    radius: Theme.tokens.radius.r8
    color: Theme.tokens.color.bgSidebar
    border.color: Theme.tokens.color.border
    border.width: 1

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Text {
            text: (root.busy ? "◌ " : root.status === "FAILED" ? "! " : "✓ ") + root.label
            font.pixelSize: 11
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }
        Text {
            Layout.fillWidth: true
            text: root.text
            font.pixelSize: 11
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
    }
}
