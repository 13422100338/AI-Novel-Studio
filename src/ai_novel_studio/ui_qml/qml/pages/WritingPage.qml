import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property bool useWebEngine: false
    property string lastEditorChapterId: ""

    Rectangle {
        anchors.fill: parent
        color: Theme.tokens.color.bgCanvas
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    text: Facade.currentVolumeTitle
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    Layout.fillWidth: true
                    text: Facade.currentChapterTitle
                    font.pixelSize: 17
                    font.bold: true
                    elide: Text.ElideRight
                    color: Theme.tokens.color.textPrimary
                }
            }

            StatusChip {
                label: "修订"
                value: String(Facade.currentRevision)
            }
            AppButton {
                text: "章节信息"
                onClicked: infoText.text = "章节信息面板将在后续 Wave 接线。"
            }
            AppButton {
                text: "AI 参考"
                primary: true
                onClicked: Facade.toggleAiDrawer(true)
            }
            AppButton {
                objectName: "draftButton"
                text: "生成草稿"
                visible: !root.useWebEngine
                enabled: !root.useWebEngine && Facade.draftStatus !== "GENERATING" && Facade.draftStatus !== "QUEUED"
                onClicked: generationDialog.openRequested = true
            }
            AppButton {
                objectName: "cancelDraftButton"
                text: "取消生成"
                visible: !root.useWebEngine && (Facade.draftStatus === "GENERATING" || Facade.draftStatus === "QUEUED")
                onClicked: Facade.cancelDraft()
            }
        }

        Text {
            id: infoText
            Layout.fillWidth: true
            text: root.useWebEngine
                ? "WebEngine 编辑器：编辑正文并保存；草稿生成在 TextArea 模式可用。"
                : "F1 Mock 工作区：编辑正文并保存；「生成草稿」会创建一条 AI 建议（候选层，不直接改正文）。"
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.tokens.radius.r16
            color: Theme.tokens.color.bgEditor
            border.color: Theme.tokens.color.border
            border.width: 1
            clip: true

            ScrollView {
                visible: !root.useWebEngine
                anchors.fill: parent
                anchors.margins: 12

                TextArea {
                    id: editor
                    objectName: "manuscriptEditor"
                    text: Facade.currentChapterBody
                    font.family: Theme.tokens.font.manuscript
                    font.pixelSize: 15
                    color: Theme.tokens.color.textPrimary
                    selectionColor: Theme.tokens.color.accent
                    selectedTextColor: "white"
                    wrapMode: TextEdit.Wrap
                    background: null
                    placeholderText: "开始写作…"
                    placeholderTextColor: Theme.tokens.color.textSecondary
                    onTextChanged: Facade.editorTextChanged(editor.text)
                }
            }

            Loader {
                id: webEditorLoader
                anchors.fill: parent
                anchors.margins: 12
                active: root.useWebEngine

                sourceComponent: NovelEditorView {
                    id: webEditor
                    objectName: "novelEditorView"
                    editorUrl: EditorAssets.indexUrl

                    function loadCurrentChapter() {
                        var payload = {
                            chapterId: Facade.currentChapterId,
                            baseRevision: Facade.currentRevision,
                            markdown: Facade.currentChapterBody
                        }
                        webEditor.loadChapter(JSON.stringify(payload))
                    }

                    onEditorLoaded: {
                        root.lastEditorChapterId = Facade.currentChapterId
                        webEditor.loadCurrentChapter()
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            StatusChip {
                label: "字数"
                value: Facade.currentWordCountText
                tone: "accent"
            }
            StatusChip {
                label: "状态"
                value: root.statusText(Facade.editorState)
                tone: root.stateTone(Facade.editorState)
            }
            StatusChip {
                label: ""
                value: Facade.saveStatusText
                visible: Facade.editorState !== "CLEAN"
            }

            Item {
                Layout.fillWidth: true
            }

            AppButton {
                objectName: "saveButton"
                text: "保存"
                primary: true
                onClicked: root.useWebEngine ? webEditor.requestSave() : Facade.requestSave()
            }
            AppButton {
                objectName: "reloadButton"
                text: "放弃本地修改并重新载入"
                visible: Facade.editorState === "CONFLICT"
                onClicked: Facade.reloadChapter()
            }
        }
    }

    function statusText(state) {
        if (state === "DIRTY") return "编辑中"
        if (state === "SAVING") return "保存中"
        if (state === "CONFLICT") return "修订冲突"
        return "已保存"
    }

    function stateTone(state) {
        if (state === "DIRTY") return "warning"
        if (state === "SAVING") return "accent"
        if (state === "CONFLICT") return "danger"
        return "success"
    }

    GenerationConfigDialog {
        id: generationDialog
        parent: root
        anchors.centerIn: parent
    }

    function revealEvidence(position, length) {
        if (root.useWebEngine) {
            Facade.setSaveStatusText("WebEngine 编辑器定位待接线，请在 TextArea 模式使用")
            return
        }
        editor.forceActiveFocus()
        editor.select(position, position + length)
    }

    function reloadFromFacade() {
        if (root.useWebEngine && webEditorLoader.item !== null) {
            webEditorLoader.item.loadCurrentChapter()
        }
    }
}
