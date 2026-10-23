import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    objectName: "workspaceModeSwitch"
    implicitWidth: 300
    implicitHeight: 38
    radius: 10
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    Row {
        anchors.fill: parent
        anchors.margins: 3
        spacing: 3
        Repeater {
            model: [{value: "writing", title: "正文"}, {value: "outline", title: "大纲"}, {value: "notes", title: "笔记"}]
            delegate: AbstractButton {
                required property var modelData
                objectName: "mode-" + modelData.value
                width: (parent.width - parent.spacing * 2) / 3
                height: parent.height
                text: modelData.title
                Accessible.name: "切换到" + text
                onClicked: Facade.setActiveNav(modelData.value)
                background: Rectangle {
                    radius: 7
                    color: Facade.activeNav === modelData.value ? Theme.tokens.color.pressed
                         : parent.hovered ? Theme.tokens.color.hover : "transparent"
                }
                contentItem: Text {
                    text: parent.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 14
                    font.bold: Facade.activeNav === modelData.value
                    color: Facade.activeNav === modelData.value ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
                }
            }
        }
    }
}
