import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    objectName: "charactersPage"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        Text {
            text: "人物"
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        StatusChip {
            objectName: "charactersPageCount"
            label: "当前章节人物"
            value: Facade.characterCountText
            tone: "accent"
        }

        ListView {
            id: list
            objectName: "charactersList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: Facade.characterViews
            ScrollBar.vertical: ScrollBar {}

            delegate: Rectangle {
                width: list.width
                height: card.implicitHeight
                radius: Theme.tokens.radius.r12
                color: Theme.tokens.color.bgSurface
                border.color: Theme.tokens.color.border
                border.width: 1

                ColumnLayout {
                    id: card
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4

                    Text {
                        text: name
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: profile !== ""
                        text: profile
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: goal !== ""
                        text: "目标：" + goal
                        font.pixelSize: 11
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: recent !== ""
                        text: "近况：" + recent
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: Facade.characterViews.count === 0
                title: "暂无人物状态"
                body: "当前章节没有人物状态卡片；人物详情与身份冲突将在后续 Wave 接线。"
            }
        }
    }
}
