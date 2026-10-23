import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: root
    readonly property bool outlineMode: Facade.activeNav === "outline"
    readonly property bool notesMode: Facade.activeNav === "notes"
    onOutlineModeChanged: { search.text = ""; Facade.setChapterFilter("") }
    onNotesModeChanged: { search.text = ""; Facade.setChapterFilter("") }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                id: projectTitle
                Layout.fillWidth: true
                text: Facade.projectTitle
                font.pixelSize: 17
                font.bold: true
                elide: Text.ElideRight
                color: Theme.tokens.color.textPrimary
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Facade.setActiveNav("writing")
                }
            }
            Text {
                text: root.notesMode ? Facade.notes.state.documents.length + " 篇"
                    : root.outlineMode ? Facade.outline.state.headings.length + " 节" : Facade.chapterCount + " 章"
                font.pixelSize: 12
                color: Theme.tokens.color.textSecondary
            }
        }

        Text {
            Layout.fillWidth: true
            text: Facade.projectPath
            font.pixelSize: 11
            elide: Text.ElideMiddle
            color: Theme.tokens.color.textSecondary
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            AppButton {
                objectName: "newProjectButton"
                text: "新建项目"
                onClicked: newProjectDialog.open()
            }
            AppButton {
                objectName: "openProjectButton"
                text: "打开项目"
                onClicked: openFolderDialog.open()
            }
        }

        Text {
            id: projectMessage
            objectName: "projectMessage"
            Layout.fillWidth: true
            text: ""
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.danger
            visible: text !== ""
        }

        SearchField {
            id: search
            Layout.fillWidth: true
            objectName: "sidebarSearch"
            onTextChanged: { if (!root.outlineMode && !root.notesMode) Facade.setChapterFilter(text) }
        }

        OutlineNavigator {
            visible: root.outlineMode
            Layout.fillWidth: true
            Layout.fillHeight: true
            query: search.text
        }

        NotesNavigator {
            visible: root.notesMode
            Layout.fillWidth: true
            Layout.fillHeight: true
            query: search.text
        }

        ListView {
            id: chapterList
            objectName: "chapterList"
            visible: !root.outlineMode && !root.notesMode
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: Facade.chapters
            rightMargin: 12
            ScrollBar.vertical: AppScrollBar {}

            delegate: Rectangle {
                id: row
                width: Math.max(0, chapterList.width - chapterList.rightMargin)
                height: kind === "volume" ? 30 : 72
                radius: Theme.tokens.radius.r8
                color: kind === "volume" ? "transparent"
                     : Facade.currentChapterId === chapterId ? Theme.tokens.color.pressed
                     : rowMouse.containsMouse ? Theme.tokens.color.hover : "transparent"

                // Selected-chapter accent bar (same flat selection language
                // as the navigation rail).
                Rectangle {
                    width: 3
                    height: 22
                    radius: 2
                    anchors.left: parent.left
                    anchors.leftMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    visible: kind === "chapter" && Facade.currentChapterId === chapterId
                    color: Theme.tokens.color.accent
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    anchors.topMargin: 8
                    anchors.bottomMargin: 8
                    spacing: 3

                    Text {
                        Layout.fillWidth: true
                        text: title
                        font.pixelSize: kind === "volume" ? 12 : 14
                        font.bold: kind === "volume"
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        visible: kind === "chapter"
                        text: wordCountText + " 字"
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: kind === "chapter"
                    onClicked: Facade.selectChapter(index)
                }
            }
        }

        GridLayout {
            visible: !root.outlineMode && !root.notesMode
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 6
            rowSpacing: 6

            AppButton {
                objectName: "newVolumeButton"
                Layout.fillWidth: true
                text: "新建卷"
                enabled: Facade.projectSource === "project" && !Facade.agentBusy
                onClicked: newVolumeDialog.open()
            }
            AppButton {
                objectName: "newChapterButton"
                Layout.fillWidth: true
                text: "新建章"
                enabled: Facade.projectSource === "project" && !Facade.agentBusy
                onClicked: newChapterDialog.open()
            }
            AppButton {
                objectName: "importManuscriptButton"
                Layout.fillWidth: true
                text: "导入稿件"
                enabled: Facade.projectSource === "project" && !Facade.agentBusy
                onClicked: manuscriptImportDialog.open()
            }
            AppButton {
                objectName: "deleteEmptyChaptersButton"
                Layout.fillWidth: true
                text: "清理空章"
                enabled: Facade.projectSource === "project" && !Facade.agentBusy
                onClicked: deleteEmptyChaptersDialog.open()
            }
        }
    }

    FolderDialog {
        id: openFolderDialog
        objectName: "projectOpenDialog"
        title: "选择项目目录"
        onAccepted: {
            var error = Facade.openProjectFromUrl(openFolderDialog.selectedFolder)
            projectMessage.text = error
        }
    }

    NewProjectDialog {
        id: newProjectDialog
        objectName: "newProjectDialog"
        onProjectCreated: function (message) {
            projectMessage.text = message
        }
    }

    StudioDialog {
        id: newVolumeDialog
        objectName: "newVolumeDialog"
        title: "新建卷"

        function submit() {
            var error = Facade.createVolume(volumeNameInput.text)
            if (error === "") {
                close()
                projectMessage.text = ""
            } else {
                volumeError.text = error
            }
        }

        onOpened: {
            volumeNameInput.text = ""
            volumeError.text = ""
            Qt.callLater(function() { volumeNameInput.forceActiveFocus() })
        }

        footer: Item {
            implicitHeight: 70
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                AppButton {
                    text: "取消"
                    ghost: true
                    onClicked: newVolumeDialog.reject()
                }
                AppButton {
                    objectName: "createVolumeConfirmButton"
                    text: "创建卷"
                    primary: true
                    enabled: volumeNameInput.text.trim() !== ""
                    onClicked: newVolumeDialog.submit()
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 14
            Text {
                Layout.fillWidth: true
                text: "为故事添加一卷，继续整理卷内的章节。"
                wrapMode: Text.Wrap
                font.pixelSize: 13
                color: Theme.tokens.color.textSecondary
            }
            Label { text: "卷名"; color: Theme.tokens.color.textSecondary }
            AppTextField {
                id: volumeNameInput
                objectName: "newVolumeNameInput"
                Layout.fillWidth: true
                implicitHeight: 42
                font.pixelSize: 14
                placeholderText: "例如：第二卷 · 远行"
                onAccepted: { if (text.trim() !== "") newVolumeDialog.submit() }
            }
            Label {
                id: volumeError
                Layout.fillWidth: true
                visible: text !== ""
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.danger
            }
        }
    }

    StudioDialog {
        id: newChapterDialog
        objectName: "newChapterDialog"
        title: "新建章节"

        function submit() {
            var error = Facade.createChapter(
                chapterTitleInput.text, chapterNumberInput.text)
            if (error === "") {
                close()
                projectMessage.text = ""
            } else {
                chapterError.text = error
            }
        }

        onOpened: {
            chapterTitleInput.text = ""
            chapterNumberInput.text = ""
            chapterError.text = ""
            Qt.callLater(function() { chapterTitleInput.forceActiveFocus() })
        }

        footer: Item {
            implicitHeight: 70
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                AppButton {
                    text: "取消"
                    ghost: true
                    onClicked: newChapterDialog.reject()
                }
                AppButton {
                    objectName: "createChapterConfirmButton"
                    text: "创建章节"
                    primary: true
                    enabled: chapterTitleInput.text.trim() !== ""
                    onClicked: newChapterDialog.submit()
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 14
            Text {
                Layout.fillWidth: true
                text: "为当前卷添加一个章节，随后即可编辑正文。"
                wrapMode: Text.Wrap
                font.pixelSize: 13
                color: Theme.tokens.color.textSecondary
            }
            Label { text: "章节标题"; color: Theme.tokens.color.textSecondary }
            AppTextField {
                id: chapterTitleInput
                objectName: "newChapterTitleInput"
                Layout.fillWidth: true
                implicitHeight: 42
                font.pixelSize: 14
                placeholderText: "例如：雾中的来客"
                onAccepted: { if (text.trim() !== "") newChapterDialog.submit() }
            }
            Label { text: "章节编号（可选）"; color: Theme.tokens.color.textSecondary }
            AppTextField {
                id: chapterNumberInput
                objectName: "newChapterNumberInput"
                Layout.fillWidth: true
                implicitHeight: 42
                font.pixelSize: 14
                placeholderText: "例如：第1章"
                onAccepted: {
                    if (chapterTitleInput.text.trim() !== "") newChapterDialog.submit()
                }
            }
            Label {
                id: chapterError
                Layout.fillWidth: true
                visible: text !== ""
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.danger
            }
        }
    }

    FileDialog {
        id: manuscriptImportDialog
        objectName: "manuscriptImportDialog"
        title: "选择 Markdown 或 TXT 稿件"
        fileMode: FileDialog.OpenFile
        nameFilters: [
            "稿件文件 (*.md *.txt)",
            "Markdown (*.md)",
            "纯文本 (*.txt)"
        ]
        onAccepted: {
            var error = Facade.importManuscriptFromUrl(selectedFile)
            projectMessage.text = error
        }
    }

    Dialog {
        id: deleteEmptyChaptersDialog
        objectName: "deleteEmptyChaptersDialog"
        property int emptyCount: 0
        title: "清理空白章节"
        modal: true
        width: 390
        standardButtons: Dialog.Cancel

        onOpened: {
            emptyCount = Facade.emptyChapterCount()
            cleanupError.text = ""
        }

        footer: DialogButtonBox {
            Button {
                text: "确认清理"
                enabled: deleteEmptyChaptersDialog.emptyCount > 0
                onClicked: {
                    var error = Facade.deleteEmptyChapters()
                    if (error === "") {
                        deleteEmptyChaptersDialog.close()
                        projectMessage.text = ""
                    } else {
                        cleanupError.text = error
                    }
                }
            }
            Button {
                text: "取消"
                onClicked: deleteEmptyChaptersDialog.reject()
            }
        }

        ColumnLayout {
            width: parent.width
            spacing: 8
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: deleteEmptyChaptersDialog.emptyCount > 0
                      ? "发现 " + deleteEmptyChaptersDialog.emptyCount
                        + " 个正文为空的章节。确认后将移入项目回收站。"
                      : "没有发现空白章节。"
                color: Theme.tokens.color.textPrimary
            }
            Label {
                id: cleanupError
                Layout.fillWidth: true
                visible: text !== ""
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.danger
            }
        }
    }
}
