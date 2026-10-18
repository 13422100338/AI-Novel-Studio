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

        GridLayout {
            id: characterPanels
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: width >= 560 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 12

            ListView {
                id: list
                objectName: "charactersList"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: characterPanels.columns === 2 && detail.visible
                    ? Math.min(320, (characterPanels.width - 12) * 0.46) : characterPanels.width
                Layout.preferredHeight: characterPanels.columns === 1 && detail.visible ? 180 : 400
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: Facade.characterViews
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    objectName: "characterCard"
                    width: list.width
                    height: Math.max(56, card.implicitHeight + 20)
                    radius: Theme.tokens.radius.r12
                    color: Facade.characterDetailVisible && Facade.characterDetailName === name
                        ? Theme.tokens.color.pressed : Theme.tokens.color.bgSurface
                    border.color: Theme.tokens.color.border
                    border.width: 1

                    ColumnLayout {
                        id: card
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 10
                        spacing: 4

                        Text {
                            objectName: "characterName"
                            Layout.fillWidth: true
                            text: name
                            font.pixelSize: 13
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
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
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: Facade.selectCharacter(index)
                    }
                }

                EmptyState {
                    anchors.fill: parent
                    visible: list.count === 0
                    title: "暂无人物状态"
                    body: "当前章节没有人物状态卡片；身份冲突将在后续 Wave 接线。"
                }
            }

            Rectangle {
                id: detail
                objectName: "characterDetail"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: characterPanels.columns === 2
                    ? characterPanels.width - 12 - list.Layout.preferredWidth : characterPanels.width
                Layout.preferredHeight: 300
                Layout.fillHeight: true
                visible: Facade.characterDetailVisible
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
                            text: Facade.characterDetailName
                            font.pixelSize: 16
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                            wrapMode: Text.WordWrap
                        }
                        AppButton {
                            objectName: "closeCharacterDetailButton"
                            text: "关闭"
                            onClicked: Facade.closeCharacterDetail()
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailProfile !== ""
                        text: "档案：" + Facade.characterDetailProfile
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailLocation !== ""
                        text: "位置：" + Facade.characterDetailLocation
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailInjury !== ""
                        text: "伤势：" + Facade.characterDetailInjury
                        font.pixelSize: 12
                        color: Theme.tokens.color.warning
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailMotivation !== ""
                        text: "动机：" + Facade.characterDetailMotivation
                        font.pixelSize: 12
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailPsychology !== ""
                        text: "心理：" + Facade.characterDetailPsychology
                        font.pixelSize: 12
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailGoal !== ""
                        text: "目标：" + Facade.characterDetailGoal
                        font.pixelSize: 12
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailRelationships !== ""
                        text: "关系：" + Facade.characterDetailRelationships
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Facade.characterDetailRecent !== ""
                        text: "近况：" + Facade.characterDetailRecent
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: Theme.tokens.color.border
                    }

                    Text {
                        text: "状态时间线"
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }

                    ListView {
                        id: journeyList
                        objectName: "characterJourneyList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: Facade.characterJourney
                        ScrollBar.vertical: ScrollBar {}

                        delegate: Rectangle {
                            objectName: "characterJourneyCard"
                            width: journeyList.width
                            height: Math.max(48, journeyCard.implicitHeight + 16)
                            radius: Theme.tokens.radius.r8
                            color: Theme.tokens.color.bgSidebar
                            border.color: Theme.tokens.color.border
                            border.width: 1

                            ColumnLayout {
                                id: journeyCard
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 8
                                spacing: 3

                                Text {
                                    text: "章节 " + chapterId
                                    font.pixelSize: 11
                                    font.bold: true
                                    color: Theme.tokens.color.accent
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: motivation !== ""
                                    text: "动机：" + motivation
                                    font.pixelSize: 11
                                    color: Theme.tokens.color.textPrimary
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: psychology !== ""
                                    text: "心理：" + psychology
                                    font.pixelSize: 11
                                    color: Theme.tokens.color.textPrimary
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: goal !== ""
                                    text: "目标：" + goal
                                    font.pixelSize: 11
                                    color: Theme.tokens.color.textPrimary
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: recent !== ""
                                    text: "近况：" + recent
                                    font.pixelSize: 11
                                    color: Theme.tokens.color.textSecondary
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
