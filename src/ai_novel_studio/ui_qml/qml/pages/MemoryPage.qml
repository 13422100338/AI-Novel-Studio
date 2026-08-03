import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
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

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            ListView {
                id: list
                objectName: "memoryList"
                Layout.preferredWidth: 320
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: Facade.memoryViews
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    width: list.width
                    height: card.implicitHeight
                    radius: Theme.tokens.radius.r12
                    color: Facade.memoryDetailVisible && Facade.memoryDetailTitle === title
                        ? Theme.tokens.color.pressed : Theme.tokens.color.bgSurface
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

                    MouseArea {
                        anchors.fill: parent
                        onClicked: Facade.selectMemory(index)
                    }
                }

                EmptyState {
                    anchors.fill: parent
                    visible: Facade.memoryViews.count === 0
                    title: "暂无记忆记录"
                    body: "当前章节没有记忆记录；整理与待确认流程将在后续 Wave 接线。"
                }
            }

            Rectangle {
                id: detail
                objectName: "memoryDetail"
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: Facade.memoryDetailVisible
                radius: Theme.tokens.radius.r12
                color: Theme.tokens.color.bgSurface
                border.color: Theme.tokens.color.border
                border.width: 1
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            text: Facade.memoryDetailTitle
                            font.pixelSize: 16
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        AppButton {
                            objectName: "closeMemoryDetailButton"
                            text: "关闭"
                            onClicked: Facade.closeMemoryDetail()
                        }
                    }

                    Text {
                        text: Facade.memoryDetailCategory + " · " + Facade.memoryDetailSourceType
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: Facade.memoryDetailContent !== ""
                        text: Facade.memoryDetailContent
                        font.pixelSize: 13
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                    }

                    Item {
                        Layout.fillHeight: true
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: Theme.tokens.color.border
                    }

                    Text {
                        text: "权威：" + Facade.memoryDetailAuthority
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                    }
                    Text {
                        text: "状态：" + Facade.memoryDetailStatus
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                    }
                    Text {
                        text: "复核：" + Facade.memoryDetailReview
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                    }
                    Text {
                        text: "修订：" + Facade.memoryDetailRevision
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                    }
                }
            }
        }
    }
}
