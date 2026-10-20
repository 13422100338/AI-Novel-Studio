import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "outlinePage"
    readonly property var outline: Facade.outline
    readonly property var view: outline.state
    property bool reimportMode: false
    onVisibleChanged: { if (!visible && linksPanel) linksPanel.close() }

    Connections {
        target: root.outline
        function onRevealRequested(position) { root.jumpTo(position) }
    }

    component PaperDialog: Dialog {
        id: paperDialog
        property string acceptText: "确认应用"
        parent: root
        anchors.centerIn: parent
        modal: true
        width: Math.min(380, root.width - 24)
        padding: 18
        background: Rectangle {
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
            radius: 12
        }
        header: Text {
            text: paperDialog.title
            leftPadding: 18
            topPadding: 16
            bottomPadding: 12
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }
        footer: DialogButtonBox {
            padding: 14
            spacing: 8
            alignment: Qt.AlignRight
            background: Rectangle { color: Theme.tokens.color.bgSurface; radius: 12 }
            AppButton { text: "取消"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            AppButton {
                objectName: paperDialog.objectName + "-accept"
                text: paperDialog.acceptText
                primary: true
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }

    function jumpTo(position) {
        editor.cursorPosition = position
        editor.forceActiveFocus()
        const rect = editor.positionToRectangle(position)
        if (sourceScroll.contentItem && sourceScroll.contentItem.contentY !== undefined)
            sourceScroll.contentItem.contentY = Math.max(0, rect.y - sourceScroll.height / 3)
    }

    Shortcut {
        sequences: [StandardKey.Save]
        enabled: root.visible && root.view.loaded
        onActivated: root.outline.flush()
    }
    Shortcut {
        sequences: [StandardKey.Find]
        enabled: root.visible && root.view.loaded
        onActivated: { contentsDrawer.open(); headingSearch.forceActiveFocus() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "大纲"
                font.pixelSize: 25
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "outlineNewButton"
                text: "新建"
                enabled: root.view.available
                onClicked: newDocumentDialog.open()
            }
            AppButton {
                objectName: "outlineImportButton"
                text: "导入"
                enabled: root.view.available
                onClicked: { root.reimportMode = false; importDialog.open() }
            }
            AppButton {
                objectName: "outlineSaveButton"
                text: "保存"
                primary: true
                enabled: root.view.loaded
                onClicked: root.outline.flush()
            }
            AppButton {
                objectName: "outlineMenuButton"
                text: "···"
                enabled: root.view.currentId !== ""
                Accessible.name: "大纲文档操作"
                onClicked: actionsMenu.popup()
                Menu {
                    id: actionsMenu
                    background: Rectangle { color: Theme.tokens.color.bgSurface; radius: 8; border.color: Theme.tokens.color.border }
                    MenuItem { text: "版本历史"; enabled: root.view.loaded; onTriggered: historyDrawer.open() }
                    MenuItem { text: "重新导入…"; enabled: root.view.loaded; onTriggered: { root.reimportMode = true; importDialog.open() } }
                    MenuItem { text: "导出当前编辑…"; enabled: root.view.loaded; onTriggered: exportDialog.open() }
                    MenuSeparator {}
                    MenuItem { text: "文档上移"; enabled: root.view.currentIndex > 0; onTriggered: root.outline.moveDocument(-1) }
                    MenuItem { text: "文档下移"; enabled: root.view.currentIndex >= 0 && root.view.currentIndex < root.view.documents.length - 1; onTriggered: root.outline.moveDocument(1) }
                    MenuSeparator {}
                    MenuItem { text: "重新载入当前文档…"; onTriggered: reloadDialog.open() }
                    MenuItem { text: "检查并接纳磁盘副本…"; onTriggered: { if (root.outline.previewDisk()) previewDialog.open() } }
                    MenuItem { text: "恢复缺失的工作文件"; enabled: !root.view.loaded; onTriggered: root.outline.restoreMissing() }
                }
            }
        }

        RowLayout {
            visible: root.view.documents.length > 0
            Layout.fillWidth: true
            ComboBox {
                id: documentsBox
                objectName: "outlineDocuments"
                Layout.fillWidth: true
                model: root.view.documents
                textRole: "title"
                valueRole: "id"
                currentIndex: root.view.currentIndex
                onActivated: root.outline.selectDocument(currentValue)
                background: Rectangle { color: Theme.tokens.color.bgSurface; radius: 8; border.color: Theme.tokens.color.border }
                contentItem: Text {
                    text: documentsBox.displayText
                    leftPadding: 12
                    rightPadding: 28
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    color: Theme.tokens.color.textPrimary
                    font.pixelSize: 14
                }
                popup.background: Rectangle { color: Theme.tokens.color.bgSurface; radius: 8; border.color: Theme.tokens.color.border }
            }
            AppButton {
                objectName: "outlineContentsButton"
                text: "目录"
                ghost: true
                enabled: root.view.loaded
                onClicked: contentsDrawer.open()
            }
            AppButton {
                objectName: "outlineLinksButton"
                text: "章节关联" + (root.view.pendingLinkCount > 0 ? " · " + root.view.pendingLinkCount : "")
                ghost: true
                enabled: root.view.loaded
                onClicked: { root.outline.refreshLinks(); linksPanel.open() }
            }
        }

        RowLayout {
            visible: root.view.loaded
            Layout.fillWidth: true
            Text {
                text: "Markdown"
                font.pixelSize: 12
                color: Theme.tokens.color.accent
            }
            Text {
                text: "修订 " + root.view.revision + " · " + (root.view.dirty ? "未保存" : root.view.status)
                font.pixelSize: 12
                color: root.view.dirty ? Theme.tokens.color.warning : Theme.tokens.color.textSecondary
            }
            Item { Layout.fillWidth: true }
            Text {
                text: root.view.text.length.toLocaleString() + " 字符"
                font.pixelSize: 12
                color: Theme.tokens.color.textSecondary
            }
        }

        Rectangle {
            visible: root.view.error !== ""
            Layout.fillWidth: true
            implicitHeight: errorText.implicitHeight + 24
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.danger
            radius: 8
            Text {
                id: errorText
                anchors.fill: parent
                anchors.margins: 12
                text: root.view.error + (root.view.dirty ? " 当前编辑已保留，可在文档菜单导出副本。" : "")
                color: Theme.tokens.color.danger
                wrapMode: Text.WordWrap
                font.pixelSize: 13
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.tokens.color.bgSurface
            radius: 12
            border.color: Theme.tokens.color.border
            clip: true

            ScrollView {
                id: sourceScroll
                anchors.fill: parent
                visible: root.view.loaded
                clip: true
                contentWidth: availableWidth
                TextArea {
                    id: editor
                    objectName: "outlineEditor"
                    width: sourceScroll.availableWidth
                    text: root.view.text
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    persistentSelection: true
                    readOnly: !root.view.loaded
                    font.family: Theme.tokens.font.mono
                    font.pixelSize: 16
                    color: Theme.tokens.color.textPrimary
                    selectionColor: Theme.tokens.color.accent
                    selectedTextColor: "white"
                    padding: 22
                    background: null
                    onTextChanged: root.outline.edit(text)
                }
            }
            EmptyState {
                anchors.fill: parent
                visible: !root.view.loaded
                title: !root.view.available ? "打开小说项目" : root.view.error !== "" ? "大纲尚未载入" : "从完整大纲开始"
                body: !root.view.available ? "打开项目后，即可导入或编写大纲。" : root.view.error !== "" ? "请检查文档菜单中的重载与恢复选项。" : "导入已有 Markdown 大纲，或新建文档，从任意事件开始细化。"
            }
        }
    }

    OutlineLinksPanel {
        id: linksPanel
        parent: root
        outline: root.outline
        sourceLine: editor.text.substring(0, editor.cursorPosition).split("\n").length
        onRevealRequested: function(position) { root.jumpTo(position) }
    }

    Popup {
        id: contentsDrawer
        objectName: "outlineContentsDrawer"
        parent: root
        x: 0
        y: 0
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: Math.min(300, root.width)
        height: root.height
        background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 10 }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            RowLayout {
                Text { text: "大纲目录"; font.bold: true; font.pixelSize: 17; color: Theme.tokens.color.textPrimary }
                Item { Layout.fillWidth: true }
                AppButton { text: "×"; ghost: true; onClicked: contentsDrawer.close() }
            }
            TextField {
                id: headingSearch
                Layout.fillWidth: true
                placeholderText: "筛选标题；回车查找正文"
                color: Theme.tokens.color.textPrimary
                background: Rectangle { color: Theme.tokens.color.bgCanvas; border.color: Theme.tokens.color.border; radius: 6 }
                onAccepted: {
                    let position = editor.text.indexOf(text, editor.cursorPosition + 1)
                    if (position < 0) position = editor.text.indexOf(text)
                    if (text && position >= 0) { contentsDrawer.close(); root.jumpTo(position) }
                }
            }
            ListView {
                id: headingsList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.view.headings.filter(function(item) { return item.title.toLowerCase().indexOf(headingSearch.text.toLowerCase()) >= 0 })
                delegate: ItemDelegate {
                    required property var modelData
                    objectName: "outline-heading-" + modelData.line
                    width: headingsList.width
                    leftPadding: 8 + Math.min(6, modelData.level - 1) * 10
                    contentItem: Text { text: modelData.title; elide: Text.ElideRight; color: Theme.tokens.color.textPrimary; font.pixelSize: 13 }
                    onClicked: { contentsDrawer.close(); root.jumpTo(modelData.position) }
                }
            }
        }
    }

    Popup {
        id: historyDrawer
        objectName: "outlineHistoryDrawer"
        parent: root
        x: Math.max(0, root.width - width)
        y: 0
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: Math.min(320, root.width)
        height: root.height
        background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 10 }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            RowLayout {
                Text { text: "版本历史"; font.bold: true; font.pixelSize: 17; color: Theme.tokens.color.textPrimary }
                Item { Layout.fillWidth: true }
                AppButton { text: "×"; ghost: true; onClicked: historyDrawer.close() }
            }
            ListView {
                id: versionsList
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.view.versions
                clip: true
                delegate: ItemDelegate {
                    required property var modelData
                    width: versionsList.width
                    contentItem: Text { text: "修订 " + modelData.revision + "    " + modelData.time; color: Theme.tokens.color.textPrimary; font.pixelSize: 13 }
                    onClicked: { if (root.outline.previewVersion(modelData.revision)) { historyDrawer.close(); previewDialog.open() } }
                }
            }
        }
    }

    PaperDialog {
        id: newDocumentDialog
        objectName: "outlineNewDialog"
        title: "新建大纲文档"
        acceptText: "新建"
        contentItem: TextField {
            id: newTitle
            objectName: "outlineNewTitle"
            text: "全书大纲"
            color: Theme.tokens.color.textPrimary
            selectByMouse: true
            selectionColor: Theme.tokens.color.accent
            selectedTextColor: "white"
            padding: 10
            background: Rectangle { color: Theme.tokens.color.bgCanvas; radius: 8; border.color: Theme.tokens.color.border }
        }
        onOpened: { newTitle.selectAll(); newTitle.forceActiveFocus() }
        onAccepted: root.outline.newDocument(newTitle.text)
    }

    PaperDialog {
        id: previewDialog
        objectName: "outlinePreviewDialog"
        width: Math.max(280, root.width - 24)
        height: Math.max(300, root.height - 24)
        title: root.view.previewKind === "reimport" ? "重新导入 · 差异预览" : root.view.previewKind === "disk" ? "检查磁盘副本" : "历史版本预览"
        acceptText: root.view.previewKind === "disk" ? "接纳磁盘版" : "确认应用"
        contentItem: ColumnLayout {
            Text { Layout.fillWidth: true; text: root.view.previewSummary; wrapMode: Text.WordWrap; color: Theme.tokens.color.textSecondary }
            ScrollView {
                id: previewScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                TextArea { width: previewScroll.availableWidth; text: root.view.previewText; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.family: Theme.tokens.font.mono; color: Theme.tokens.color.textPrimary; background: null }
            }
        }
        onAccepted: root.outline.applyPreview()
    }

    PaperDialog {
        id: reloadDialog
        title: "重新载入大纲？"
        acceptText: "放弃编辑并重载"
        contentItem: Text { text: "未保存的本地编辑将被放弃。\n可先取消并导出副本；已保存历史保留。"; color: Theme.tokens.color.textPrimary }
        onAccepted: root.outline.reloadDocument(true)
    }

    FileDialog {
        id: importDialog
        title: root.reimportMode ? "选择重新导入的大纲" : "导入大纲"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Markdown 与文本 (*.md *.markdown *.txt)"]
        onAccepted: {
            if (root.reimportMode) {
                if (root.outline.previewReimport(selectedFile)) previewDialog.open()
            } else root.outline.importFile(selectedFile)
        }
    }
    FileDialog {
        id: exportDialog
        title: "导出当前编辑 · 请选择新文件名"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "md"
        nameFilters: ["Markdown (*.md)", "文本 (*.txt)"]
        onAccepted: root.outline.exportFile(selectedFile)
    }
}
