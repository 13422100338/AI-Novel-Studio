import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: Facade.projectTitle
                font.pixelSize: 15
                font.bold: true
                elide: Text.ElideRight
                color: Theme.tokens.color.textPrimary
            }
            Text {
                text: Facade.chapterCount + " 章"
                font.pixelSize: 11
                color: Theme.tokens.color.textSecondary
            }
        }

        Text {
            Layout.fillWidth: true
            text: Facade.projectPath
            font.pixelSize: 10
            elide: Text.ElideMiddle
            color: Theme.tokens.color.textSecondary
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            AppButton {
                objectName: "openProjectButton"
                text: "打开项目"
                onClicked: openFolderDialog.open()
            }
            AppButton {
                objectName: "resetDemoButton"
                text: "重置演示"
                onClicked: {
                    projectMessage.text = ""
                    Facade.closeProject()
                }
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
            onTextChanged: Facade.setChapterFilter(text)
        }

        ListView {
            id: chapterList
            objectName: "chapterList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: Facade.chapters
            ScrollBar.vertical: ScrollBar {}

            delegate: Rectangle {
                id: row
                width: chapterList.width
                height: kind === "volume" ? 28 : 46
                radius: Theme.tokens.radius.r8
                color: kind === "volume" ? "transparent"
                     : Facade.currentChapterId === chapterId ? Theme.tokens.color.pressed
                     : rowMouse.containsMouse ? Theme.tokens.color.hover : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        text: title
                        font.pixelSize: kind === "volume" ? 11 : 13
                        font.bold: kind === "volume"
                        elide: Text.ElideRight
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        visible: kind === "chapter"
                        text: wordCountText
                        font.pixelSize: 10
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
}
