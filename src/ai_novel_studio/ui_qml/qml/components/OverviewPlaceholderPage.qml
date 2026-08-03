import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property string title: ""
    property string countLabel: ""
    property string countText: "—"
    property string description: ""

    Rectangle {
        anchors.fill: parent
        color: Theme.tokens.color.bgCanvas
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 12

        Text {
            text: root.title
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        StatusChip {
            objectName: root.objectName + "Count"
            label: root.countLabel
            value: root.countText
            tone: "accent"
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        EmptyState {
            anchors.centerIn: parent
            title: "页面迁移中"
            body: root.description
        }
    }
}

