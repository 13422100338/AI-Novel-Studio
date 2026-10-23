import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    objectName: "notesNavigator"
    property string query: ""
    readonly property var notes: Facade.notes
    readonly property var view: notes.state
    spacing: 10
    Text { text: "创作笔记"; font.pixelSize: 12; font.bold: true; color: Theme.tokens.color.textSecondary }
    Text {
        Layout.fillWidth: true
        text: "细纲、人物、文风与注意事项"
        font.pixelSize: 11
        color: Theme.tokens.color.textSecondary
        wrapMode: Text.WordWrap
    }
    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 5
        model: root.view.documents.filter(function(n) { return n.title.toLowerCase().indexOf(root.query.toLowerCase()) >= 0 })
        ScrollBar.vertical: AppScrollBar { visible: size < 1 }
        delegate: ItemDelegate {
            required property var modelData
            objectName: "note-nav-" + modelData.id
            width: list.width - 10
            implicitHeight: Math.max(66, label.implicitHeight + 24)
            padding: 10
            onClicked: root.notes.selectDocument(modelData.id)
            background: Rectangle {
                radius: 9
                color: root.view.currentId === modelData.id ? Theme.tokens.color.pressed : parent.hovered ? Theme.tokens.color.hover : "transparent"
            }
            contentItem: RowLayout {
                spacing: 5
                NoteCheckBox {
                    objectName: "note-check-" + modelData.id
                    checked: root.view.selectedIds.indexOf(modelData.id) >= 0
                    enabled: !Facade.agentBusy
                    onClicked: root.notes.toggleSelected(modelData.id, checked)
                    Accessible.name: "本次写作引用 " + modelData.title
                }
                ColumnLayout {
                    id: label
                    spacing: 6
                    Text {
                        Layout.fillWidth: true
                        text: modelData.title
                        font.pixelSize: 13
                        font.bold: root.view.currentId === modelData.id
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        text: ({OUTLINE: "细纲", CHARACTER: "人物", STYLE: "文风", CAUTION: "注意事项", OTHER: "其他"})[modelData.kind] + " · 修订 " + modelData.revision
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }
                }
            }
        }
        Text {
            anchors.centerIn: parent
            width: parent.width - 16
            visible: list.count === 0
            text: root.view.documents.length ? "没有匹配的笔记" : "新建或导入笔记\n把商讨结果留在这里"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 12
        }
    }
}
