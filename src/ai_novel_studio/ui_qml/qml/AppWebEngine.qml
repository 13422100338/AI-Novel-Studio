import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"

ApplicationWindow {
    id: window
    objectName: "webEngineWindow"

    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 680
    visible: true
    title: "AI Novel Studio (WebEngine Phase 1)"
    color: Theme.tokens.color.bgCanvas

    property bool sidebarVisible: true

    RowLayout {
        anchors.fill: parent
        spacing: 0

        NavigationRail {
            Layout.preferredWidth: 56
            Layout.fillHeight: true
        }

        Rectangle {
            Layout.preferredWidth: window.sidebarVisible ? 280 : 0
            Layout.fillHeight: true
            color: Theme.tokens.color.bgSidebar
            clip: true

            ContextSidebar {
                anchors.fill: parent
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        Layout.fillWidth: true
                        text: Facade.currentChapterTitle
                        font.pixelSize: 16
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    AppButton {
                        objectName: "webSaveButton"
                        text: "保存"
                        primary: true
                        onClicked: editorView.requestSave()
                    }
                }

                NovelEditorView {
                    id: editorView
                    objectName: "novelEditorView"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    editorUrl: EditorAssets.indexUrl

                    onEditorLoaded: {
                        // Handshake + load the current chapter once the page is up.
                        var payload = {
                            chapterId: Facade.currentChapterId,
                            baseRevision: Facade.currentRevision,
                            markdown: Facade.currentChapterBody
                        }
                        editorView.loadChapter(JSON.stringify(payload))
                    }
                }
            }
        }
    }
}
