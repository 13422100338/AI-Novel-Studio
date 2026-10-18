import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "choiceCard"

    property var options: []
    signal chosen(int index)

    width: parent ? parent.width : 320
    implicitHeight: Math.max(30, column.implicitHeight + 12)
    radius: Theme.tokens.radius.r12
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        Repeater {
            model: root.options
            delegate: AppButton {
                Layout.fillWidth: true
                text: modelData
                onClicked: root.chosen(index)
            }
        }
    }
}
