import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../surfaces"

Item {
    id: root

    property bool useWebEngine: false
    property string lastEditorChapterId: ""
    // 2026-08-26 ticket: fixed-copy load failure banner. Non-empty means the
    // editor is showing an error state instead of chapter body text.
    property string chapterLoadErrorText: ""
    // Window backdrop passed from the shell; the manuscript host becomes an
    // Acrylic surface over it (same glass language as nav/sidebar/dock).
    property Item backdropSource: null

    Rectangle {
        anchors.fill: parent
        color: Theme.tokens.color.bgCanvas
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Text {
                    text: Facade.currentVolumeTitle
                    font.pixelSize: 12
                    font.letterSpacing: 0.6
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    Layout.fillWidth: true
                    text: Facade.currentChapterTitle
                    font.family: Theme.tokens.font.manuscript
                    font.pixelSize: 27
                    font.bold: true
                    elide: Text.ElideRight
                    color: Theme.tokens.color.textPrimary
                }
            }

            AppButton {
                objectName: "chapterSaveButton"
                text: "保存"
                primary: true
                visible: Facade.chapterCount > 0
                onClicked: root.save()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: Facade.chapterCount > 0
            Text {
                Layout.fillWidth: true
                text: "修订 " + Facade.currentRevision + " · "
                    + (Facade.editorState === "CLEAN" ? "已保存" : Facade.saveStatusText)
                font.pixelSize: 11
                color: Theme.tokens.color.textSecondary
                wrapMode: Text.WordWrap
            }
            AppButton {
                objectName: "chapterReloadButton"
                text: "放弃本地修改并重载"
                visible: Facade.editorState === "CONFLICT"
                enabled: visible
                onClicked: Facade.reloadChapter()
            }
        }

        // Manuscript host: flat opaque "paper" panel (clean modern shell).
        // In TextArea mode the editor sits directly on the surface; in
        // WebEngine mode the page background (theme-synced) stays opaque on
        // top for readability while the rounded rim frames the sheet.
        AcrylicSurface {
            objectName: "manuscriptHost"
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.tokens.radius.r12
            sourceItem: root.backdropSource
            opaqueFallback: true
            clip: true

            // Production empty state: no project (or an untouched new one)
            // shows an honest placeholder instead of a bare editor.
            EmptyState {
                objectName: "writingEmptyState"
                anchors.fill: parent
                visible: Facade.chapterCount === 0
                title: Facade.projectSource === "empty"
                       ? "未打开项目" : "还没有章节"
                body: Facade.projectSource === "empty"
                             ? "从左上角新建或打开一个项目开始写作。"
                             : "在左侧章节列表下方新建第一章。"
            }

            ScrollView {
                visible: !root.useWebEngine && Facade.chapterCount > 0
                anchors.fill: parent
                anchors.margins: 12

                TextArea {
                    id: editor
                    objectName: "manuscriptEditor"
                    text: Facade.currentChapterBody
                    font.family: Theme.tokens.font.manuscript
                    font.pixelSize: 17
                    color: Theme.tokens.color.textPrimary
                    selectionColor: Theme.tokens.color.accent
                    selectedTextColor: "white"
                    wrapMode: TextEdit.Wrap
                    background: null
                    placeholderText: "开始写作…"
                    placeholderTextColor: Theme.tokens.color.textSecondary
                    onTextChanged: Facade.editorTextChanged(editor.text)
                    onSelectedTextChanged: {
                        if (!root.useWebEngine) {
                            Facade.setPlainTextSelection(editor.selectionStart, editor.selectionEnd)
                        }
                    }
                }
            }

            Loader {
                id: webEditorLoader
                anchors.fill: parent
                active: root.useWebEngine && Facade.chapterCount > 0

                sourceComponent: NovelEditorView {
                    id: webEditor
                    objectName: "novelEditorView"
                    editorUrl: EditorAssets.indexUrl
                    // Static: QtWebEngine must not re-bind its canvas color to
                    // the live bridge (crashes on capability emit). The
                    // manuscript host around it is the glass; the editor
                    // sheet stays on the theme editor color for readability.
                    editorSurfaceColor: Theme.tokens.color.bgEditor

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
                    onDocumentLoaded: function(chapterId, revision, wordCount) {
                        root.chapterLoadErrorText = ""
                    }
                    onDocumentLoadFailed: function(reason) {
                        root.chapterLoadErrorText = reason === "UNSUPPORTED_MARKDOWN"
                                ? "当前章节包含编辑器暂不支持的 Markdown 语法，正文未切换。"
                                : "章节正文加载失败，请重新选择章节。"
                        Facade.setSaveStatusText(root.chapterLoadErrorText)
                        // Allow an explicit re-click on the same chapter to
                        // retry; deterministic failures simply fail once more.
                        root.lastEditorChapterId = ""
                    }

                    Connections {
                        target: Facade
                        function onChapterChanged() {
                            if (webEditorLoader.item !== null
                                    && Facade.currentChapterId !== ""
                                    && root.lastEditorChapterId !== Facade.currentChapterId) {
                                root.lastEditorChapterId = Facade.currentChapterId
                                webEditorLoader.item.loadCurrentChapter()
                            }
                        }
                        function onDraftAcceptedToEditor(markdown) {
                            if (webEditorLoader.item !== null) {
                                webEditorLoader.item.loadChapter(
                                    JSON.stringify({
                                        chapterId: Facade.currentChapterId,
                                        baseRevision: Facade.currentRevision,
                                        markdown: markdown
                                    })
                                )
                            }
                        }
                        function onEditorRevisionChanged(revision) {
                            // A queued whole-document reload already carries its
                            // revision and exact Markdown. Do not acknowledge it
                            // again by serializing the freshly loaded document.
                            if (webEditorLoader.item !== null
                                    && webEditorLoader.item.pendingDocumentPayload === "") {
                                webEditorLoader.item.setBaseRevision(revision)
                            }
                        }
                    }
                }
            }

            // 2026-08-26 ticket: when a chapter fails to load, cover the
            // (stale or empty) editor surface with a fixed-copy banner so the
            // UI never shows "new title + old body". Cleared automatically on
            // the next successful load.
            Rectangle {
                objectName: "chapterLoadErrorOverlay"
                anchors.fill: parent
                anchors.margins: 12
                radius: Theme.tokens.radius.r12
                visible: root.useWebEngine && root.chapterLoadErrorText !== ""
                color: Theme.tokens.color.bgEditor

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 10
                    width: Math.min(parent.width - 48, 420)

                    Label {
                        text: "正文未加载"
                        font.pixelSize: 15
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                        Layout.alignment: Qt.AlignHCenter
                    }
                    Label {
                        text: root.chapterLoadErrorText
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.tokens.color.textSecondary
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }
        }
    }

    function save() {
        if (root.useWebEngine) {
            if (webEditorLoader.item !== null) {
                webEditorLoader.item.requestSave()
            }
        } else {
            Facade.requestSave()
        }
    }

    function revealEvidence(position, length) {
        if (root.useWebEngine) {
            if (webEditorLoader.item !== null) {
                webEditorLoader.item.revealRange(position, position + length)
            }
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
