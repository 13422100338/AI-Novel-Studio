import QtQuick

Item {
    id: root

    property string title: ""
    property string body: ""

    Column {
        anchors.centerIn: parent
        spacing: 8

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.title
            font.pixelSize: 15
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }
        Text {
            width: 360
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.body
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }
}

