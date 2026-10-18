import QtQuick

Item {
    id: root

    property string title: ""
    property string body: ""

    Column {
        width: Math.max(0, Math.min(360, root.width - 32))
        anchors.centerIn: parent
        spacing: 8

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.title
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }
        Text {
            width: parent.width
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.body
            font.pixelSize: 13
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
