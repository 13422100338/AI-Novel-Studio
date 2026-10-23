import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

AppButton {
    id: root
    objectName: "noteInputPickerButton"
    text: "笔记" + (Facade.notes.state.selectedIds.length ? " · " + Facade.notes.state.selectedIds.length : "")
    ghost: true
    enabled: Facade.notes.state.available && !Facade.agentBusy
    onClicked: { Facade.notes.refresh(); picker.open() }
    Popup {
        id: picker
        objectName: "noteInputPicker"
        parent: Overlay.overlay
        width: Math.min(360, parent ? parent.width - 32 : 360)
        height: Math.min(480, parent ? parent.height - 80 : 480)
        x: Math.max(16, parent.width - width - 30)
        y: Math.max(40, parent.height - height - 150)
        padding: 18
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 14 }
        contentItem: ColumnLayout {
            spacing: 12
            RowLayout {
                Text { text: "写作时使用的笔记"; font.pixelSize: 16; font.bold: true; color: Theme.tokens.color.textPrimary }
                Item { Layout.fillWidth: true }
                AppButton { objectName: "notePickerCloseButton"; text: "×"; ghost: true; implicitWidth: 28; onClicked: picker.close() }
            }
            NotesInputOptions { objectName: "noteInputPickerOptions"; Layout.fillWidth: true }
            Text {
                Layout.fillWidth: true
                text: "先勾选笔记，再选择原文或要点。生成前仍可检查完整输入。"
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.textSecondary
                font.pixelSize: 12
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: Facade.notes.state.documents
                ScrollBar.vertical: AppScrollBar { visible: size < 1 }
                delegate: NoteCheckBox {
                    required property var modelData
                    width: list.width - 10
                    text: modelData.title
                    checked: Facade.notes.state.selectedIds.indexOf(modelData.id) >= 0
                    onClicked: Facade.notes.toggleSelected(modelData.id, checked)
                }
                Text {
                    anchors.centerIn: parent
                    visible: list.count === 0
                    text: "尚无笔记，可从顶部“笔记”新建。"
                    color: Theme.tokens.color.textSecondary
                    font.pixelSize: 12
                }
            }
            Text {
                Layout.fillWidth: true
                visible: Facade.notes.state.error !== ""
                text: Facade.notes.state.error
                color: Theme.tokens.color.danger
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }
            AppButton { text: "管理笔记"; Layout.fillWidth: true; onClicked: { picker.close(); Facade.setActiveNav("notes") } }
        }
    }
}
