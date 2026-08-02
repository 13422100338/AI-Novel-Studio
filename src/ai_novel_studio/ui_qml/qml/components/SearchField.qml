import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property alias text: field.text
    signal textChanged(string value)

    implicitHeight: 30
    radius: Theme.tokens.radius.r8
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 4
        spacing: 6

        Text {
            text: "\u2315"
            font.pixelSize: 14
            color: Theme.tokens.color.textSecondary
        }
        TextField {
            id: field
            Layout.fillWidth: true
            placeholderText: "搜索章节"
            color: Theme.tokens.color.textPrimary
            placeholderTextColor: Theme.tokens.color.textSecondary
            background: Item {}
            onTextChanged: root.textChanged(text)
        }
    }
}

