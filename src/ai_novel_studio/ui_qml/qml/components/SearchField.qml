import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property alias text: field.text
    signal textChanged(string value)

    implicitHeight: 36
    radius: Theme.tokens.radius.r8
    color: Theme.tokens.color.bgSurface
    border.color: field.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
    border.width: field.activeFocus ? 2 : 1

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
            font.pixelSize: 13
            color: Theme.tokens.color.textPrimary
            placeholderTextColor: Theme.tokens.color.textSecondary
            background: Item {}
            onTextChanged: root.textChanged(text)
        }
    }
}
