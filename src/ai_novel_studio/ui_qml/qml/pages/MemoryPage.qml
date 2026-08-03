import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    objectName: "memoryPage"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        Text {
            text: "记忆"
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        StatusChip {
            objectName: "memoryPageCount"
            label: "当前章节记忆"
            value: Facade.memoryCountText
            tone: "accent"
        }

        ListView {
            id: list
            objectName: "memoryList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: Facade.memoryViews
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
                        text: title
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        text: category + " · " + sourceType
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: content !== ""
                        text: content
                        font.pixelSize: 12
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }
                    Text {
                        text: "状态：" + status + " · 复核：" + review + " · 修订 " + revision
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: Facade.memoryViews.count === 0
                title: "暂无记忆记录"
                body: "当前章节没有记忆记录；整理与待确认流程将在后续 Wave 接线。"
            }
        }
    }
}
