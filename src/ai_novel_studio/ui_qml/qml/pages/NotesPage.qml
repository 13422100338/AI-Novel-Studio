import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "notesPage"
    readonly property var notes: Facade.notes
    readonly property var view: notes.state
    property bool editingSource: false
    readonly property var rendered: view.loaded && !editingSource
        ? OutlineMarkup.render(view.text, view.headings, String(Theme.tokens.color.border)) : ({html: ""})
    function discuss() {
        if (!notes.flush()) return
        Facade.toggleAiDrawer(true)
        Facade.startAssistantChat("请先用 read_novel_notes 读取笔记“" + view.title + "”（note_id=" + view.currentId + "），与我讨论和完善这份笔记。现在只商讨，不调用正文模型。")
    }
    component PaperDialog: Dialog {
        id: paperDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: 18
        background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 14 }
        header: Text { text: paperDialog.title; padding: 18; font.pixelSize: 18; font.bold: true; color: Theme.tokens.color.textPrimary }
    }
    Shortcut { sequences: [StandardKey.Save]; enabled: root.visible && root.view.loaded; onActivated: root.notes.flush() }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            TextField {
                objectName: "noteTitle"
                Layout.fillWidth: true
                Layout.minimumWidth: 50
                text: root.view.title
                placeholderText: "创作笔记"
                enabled: root.view.loaded
                maximumLength: 200
                color: Theme.tokens.color.textPrimary
                placeholderTextColor: Theme.tokens.color.textSecondary
                font.pixelSize: 17
                font.bold: true
                padding: 8
                background: Rectangle { color: parent.activeFocus ? Theme.tokens.color.bgSurface : "transparent"; radius: 8 }
                onTextEdited: root.notes.setTitle(text)
            }
            AppButton {
                objectName: "noteSourceToggle"
                text: root.editingSource ? "阅读" : "编辑源码"
                enabled: root.view.loaded
                ghost: true
                onClicked: root.editingSource = !root.editingSource
            }
            AppButton { objectName: "noteNewButton"; text: "新建"; enabled: root.view.available; onClicked: newDialog.open() }
            AppButton { objectName: "noteSaveButton"; text: "保存"; primary: true; enabled: root.view.loaded; onClicked: root.notes.flush() }
            AppButton {
                text: "···"
                implicitWidth: 36
                onClicked: actions.popup()
                Menu {
                    id: actions
                    background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 10 }
                    MenuItem { text: "导入 Markdown…"; enabled: root.view.available; onTriggered: importDialog.open() }
                    MenuItem { text: "导出当前编辑…"; enabled: root.view.loaded; onTriggered: exportDialog.open() }
                    MenuItem { text: "与 Codex 讨论这篇笔记"; enabled: root.view.loaded && Facade.codexEnabled; onTriggered: root.discuss() }
                    MenuItem { text: "版本历史"; enabled: root.view.loaded; onTriggered: { history.versions = root.view.versions.slice(); version.currentIndex = root.view.revision - 1; root.notes.previewVersion(root.view.revision); history.open() } }
                    MenuItem { text: "重新载入笔记…"; enabled: root.view.loaded; onTriggered: reloadDialog.open() }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.view.loaded
            AppComboBox {
                objectName: "noteKind"
                Layout.preferredWidth: 125
                model: [{value:"OUTLINE",label:"细纲"},{value:"CHARACTER",label:"人物"},{value:"STYLE",label:"文风"},{value:"CAUTION",label:"注意事项"},{value:"OTHER",label:"其他"}]
                textRole: "label"; valueRole: "value"
                currentIndex: ["OUTLINE","CHARACTER","STYLE","CAUTION","OTHER"].indexOf(root.view.kind)
                onActivated: root.notes.setKind(currentValue)
            }
            Text { text: "修订 " + root.view.revision + " · " + root.view.status; color: Theme.tokens.color.textSecondary; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            NoteCheckBox {
                objectName: "noteUseCurrent"
                text: "用于本次写作"
                checked: root.view.selectedIds.indexOf(root.view.currentId) >= 0
                enabled: !Facade.agentBusy
                onClicked: root.notes.toggleSelected(root.view.currentId, checked)
                palette.windowText: Theme.tokens.color.textPrimary
            }
        }
        NotesInputOptions { Layout.fillWidth: true; visible: root.view.available }
        Text {
            Layout.fillWidth: true
            visible: root.view.error !== ""
            text: root.view.error
            color: Theme.tokens.color.danger
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
        AppButton {
            visible: root.view.recoveries.length > 0
            text: "有 " + root.view.recoveries.length + " 个未完成保存，查看恢复"
            Layout.fillWidth: true
            onClicked: recovery.open()
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
            radius: 12
            clip: true
            ScrollView {
                id: sourceScroll
                anchors.fill: parent
                visible: root.view.loaded && root.editingSource
                contentWidth: availableWidth
                clip: true
                TextArea {
                    id: editor
                    objectName: "noteEditor"
                    width: sourceScroll.availableWidth
                    text: root.view.text
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    font.family: Theme.tokens.font.mono
                    font.pixelSize: 16
                    color: Theme.tokens.color.textPrimary
                    padding: 24
                    background: null
                    onTextChanged: root.notes.edit(text)
                }
            }
            ScrollView {
                id: readerScroll
                anchors.fill: parent
                visible: root.view.loaded && !root.editingSource
                contentWidth: availableWidth
                clip: true
                TextArea {
                    objectName: "noteReadView"
                    width: readerScroll.availableWidth
                    text: root.rendered.html
                    textFormat: TextEdit.RichText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    font.pixelSize: 18
                    color: Theme.tokens.color.textPrimary
                    padding: 26
                    background: null
                }
            }
            EmptyState {
                anchors.fill: parent
                visible: !root.view.loaded
                title: root.view.available ? "把讨论变成可继续打磨的笔记" : "打开小说项目"
                body: "保存细纲、人物特点、文风和注意事项；何时用于正文，由你决定。"
            }
        }
        Text {
            Layout.fillWidth: true
            text: "保存或离开页面时保留修订。笔记是创作指导，保存不会启动正文模型。"
            font.pixelSize: 11
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
    }
    PaperDialog {
        id: newDialog
        title: "新建笔记"
        width: 360
        contentItem: ColumnLayout {
            TextField { id: newTitle; objectName: "noteNewTitle"; Layout.fillWidth: true; placeholderText: "例如：第25事件场景细纲"; maximumLength: 200 }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "取消"; onClicked: newDialog.close() }
                AppButton { objectName: "noteCreateConfirm"; text: "创建"; primary: true; onClicked: { if (root.notes.createNote(newTitle.text, "OTHER")) { newDialog.close(); root.editingSource = true; editor.forceActiveFocus() } } }
            }
        }
    }
    PaperDialog {
        id: reloadDialog
        title: "重新载入笔记"
        width: 380
        contentItem: ColumnLayout {
            Text { Layout.fillWidth: true; text: "将放弃当前未保存编辑并载入已保存版本。需要保留本地内容时，请先导出副本。"; wrapMode: Text.WordWrap; color: Theme.tokens.color.textPrimary }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "取消"; onClicked: reloadDialog.close() }
                AppButton { text: "确认重新载入"; onClicked: { if (root.notes.reload()) reloadDialog.close() } }
            }
        }
    }
    FileDialog { id: importDialog; title: "导入笔记"; nameFilters: ["Markdown 与文本 (*.md *.txt)"]; onAccepted: root.notes.importFile(selectedFile) }
    FileDialog { id: exportDialog; title: "导出笔记（请选择新文件）"; fileMode: FileDialog.SaveFile; defaultSuffix: "md"; nameFilters: ["Markdown (*.md)"]; onAccepted: root.notes.exportFile(selectedFile) }
    PaperDialog {
        id: history
        property var versions: []
        title: "笔记版本历史"
        width: Math.min(700, parent.width - 48)
        height: Math.min(620, parent.height - 64)
        contentItem: ColumnLayout {
            ComboBox { id: version; Layout.fillWidth: true; model: history.versions; currentIndex: -1; displayText: "修订 " + (currentIndex + 1); onActivated: root.notes.previewVersion(currentIndex + 1) }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true; TextArea { text: root.view.previewText; readOnly: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.tokens.color.textPrimary; background: null } }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "关闭"; onClicked: history.close() }
                AppButton { text: "将此版本另存为新修订"; onClicked: { if (root.notes.restoreVersion(root.view.previewRevision)) history.close() } }
            }
        }
    }
    PaperDialog {
        id: recovery
        title: "恢复未完成的笔记保存"
        width: Math.min(700, parent.width - 48)
        height: Math.min(620, parent.height - 64)
        readonly property var item: root.view.recoveries[recoveryChoice.currentIndex] || ({})
        contentItem: ColumnLayout {
            ComboBox { id: recoveryChoice; Layout.fillWidth: true; model: root.view.recoveries; textRole: "title" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true; TextArea { text: recovery.item.content || "暂存数据不完整，不能自动恢复；归档会保留原文件。"; readOnly: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.tokens.color.textPrimary; background: null } }
            Text { Layout.fillWidth: true; text: root.view.error; wrapMode: Text.WordWrap; color: Theme.tokens.color.danger }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "关闭"; onClicked: recovery.close() }
                AppButton { text: "保留并归档"; enabled: !!recovery.item.name; onClicked: { if (root.notes.recoverSaving(recovery.item.name, false) && !root.view.recoveries.length) recovery.close() } }
                AppButton { text: "恢复此暂存"; enabled: recovery.item.valid === true; onClicked: { if (root.notes.recoverSaving(recovery.item.name, true) && !root.view.recoveries.length) recovery.close() } }
            }
        }
    }
}
