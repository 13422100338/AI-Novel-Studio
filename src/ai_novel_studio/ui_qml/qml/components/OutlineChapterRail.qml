import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "outlineChapterRail"
    readonly property var outline: Facade.outline
    readonly property var navigation: outline.navigation
    readonly property var chapters: navigation.chapters
    signal manageRequested()
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    radius: 16
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12
        Text { text: "对应章节"; font.pixelSize: 16; font.bold: true; color: Theme.tokens.color.textPrimary }
        Text {
            Layout.fillWidth: true
            text: OutlineMarkup.title(root.navigation.headingTitle)
            font.pixelSize: 13
            font.bold: true
            color: Theme.tokens.color.accent
            wrapMode: Text.WordWrap
            maximumLineCount: 3
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: root.outline.state.dirty ? "编辑尚未保存，关联以已登记记录为准。"
                : "当前节点关联 " + root.chapters.length + " 个章节"
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
            font.pixelSize: 11
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            rightMargin: 8
            model: root.chapters
            ScrollBar.vertical: AppScrollBar { visible: size < 1 }
            delegate: ItemDelegate {
                required property var modelData
                objectName: "outline-linked-" + modelData.chapterId
                width: list.width - list.rightMargin
                implicitHeight: card.implicitHeight + 22
                padding: 11
                enabled: modelData.available
                onClicked: root.outline.openLinkedChapter(modelData.chapterId)
                background: Rectangle { color: parent.hovered ? Theme.tokens.color.hover : Theme.tokens.color.bgCanvas; radius: 9; border.color: Theme.tokens.color.border }
                contentItem: ColumnLayout {
                    id: card
                    spacing: 7
                    Text {
                        Layout.fillWidth: true
                        text: modelData.title || "章节不可用"
                        font.pixelSize: 13
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.confirmed ? "已确认 · 点击阅读" : modelData.status + " · 点击阅读"
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        color: modelData.confirmed ? Theme.tokens.color.success : Theme.tokens.color.accent
                    }
                }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width - 8
                visible: list.count === 0
                text: "尚无关联章节\n可在下方添加或管理关联"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: 12
                lineHeight: 1.4
                color: Theme.tokens.color.textSecondary
            }
        }
        AppButton {
            objectName: "outlineLinksButton"
            Layout.fillWidth: true
            text: "管理章节关联"
            ghost: true
            onClicked: root.manageRequested()
        }
    }
}
