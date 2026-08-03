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

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            ListView {
                id: list
                objectName: "charactersList"
                Layout.preferredWidth: 320
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: Facade.characterViews
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    width: list.width
                    height: card.implicitHeight
                    radius: Theme.tokens.radius.r12
                    color: Facade.characterDetailVisible && Facade.characterDetailName === name
                        ? Theme.tokens.color.pressed : Theme.tokens.color.bgSurface
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
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: Facade.selectCharacter(index)
                    }
                }

                EmptyState {
                    anchors.fill: parent
                    visible: Facade.characterViews.count === 0
                    title: "暂无人物状态"
                    body: "当前章节没有人物状态卡片；身份冲突将在后续 Wave 接线。"
                }
            }

            Rectangle {
                id: detail
                objectName: "characterDetail"
                Layout.fillWidth: true
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
                            width: journeyList.width
                            height: journeyCard.implicitHeight
                            radius: Theme.tokens.radius.r8
                            color: Theme.tokens.color.bgSidebar
                            border.color: Theme.tokens.color.border
                            border.width: 1

                            ColumnLayout {
                                id: journeyCard
                                anchors.fill: parent
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
