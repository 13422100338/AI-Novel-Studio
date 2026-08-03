import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// WebEngine-mode AI drawer: a true layout cell inside the central RowLayout.
// No anchors.fill and no high z, so the WebEngine native surface can never be
// covered by a floating overlay; opening this drawer simply shrinks the editor.
Rectangle {
    id: root
    objectName: "dockedAiDrawer"

    property bool open: false
    property int preferredWidth: 340
    property bool fillHeight: true
    signal closed()

    visible: root.open
    Layout.preferredWidth: root.preferredWidth
    Layout.fillHeight: root.fillHeight
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: "AI 参考"
                font.pixelSize: 15
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "dockedDrawerCloseButton"
                text: "关闭"
                onClicked: root.closed()
            }
        }

        ListView {
            id: suggestionList
            visible: !Facade.draftViewEnabled
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: Facade.suggestions
            ScrollBar.vertical: ScrollBar {}

            delegate: Rectangle {
                width: suggestionList.width
                height: card.implicitHeight
                radius: Theme.tokens.radius.r12
                color: Theme.tokens.color.bgSidebar
                border.color: Theme.tokens.color.border
                border.width: 1

                ColumnLayout {
                    id: card
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    Text {
                        text: label
                        font.pixelSize: 12
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        Layout.fillWidth: true
                        text: body
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Item {
                            Layout.fillWidth: true
                        }
                        AppButton {
                            text: "放弃"
                            onClicked: Facade.discardSuggestion(index)
                        }
                        AppButton {
                            text: "采用"
                            primary: true
                            onClicked: Facade.acceptSuggestion(index)
                        }
                    }
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: Facade.suggestions.count === 0
                title: "暂无 AI 建议"
                body: "点击「生成草稿」创建一条 Mock 建议，演示候选层流程。"
            }
        }

        ColumnLayout {
            id: draftViewer
            visible: Facade.draftViewEnabled
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 4

                AppButton {
                    objectName: "viewCurrentButton"
                    text: "当前正文"
                    selected: Facade.draftView === "current"
                    onClicked: Facade.setDraftView("current")
                }
                AppButton {
                    objectName: "viewDraftButton"
                    text: "AI 草稿"
                    selected: Facade.draftView === "draft"
                    onClicked: Facade.setDraftView("draft")
                }
                AppButton {
                    objectName: "viewDiffButton"
                    text: "修改对比"
                    selected: Facade.draftView === "diff"
                    onClicked: Facade.setDraftView("diff")
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: Facade.draftView === "current" ? 0
                    : Facade.draftView === "draft" ? 1 : 2

                Item {
                    ScrollView {
                        anchors.fill: parent
                        TextArea {
                            readOnly: true
                            text: Facade.draftBaseText
                            wrapMode: TextEdit.Wrap
                            color: Theme.tokens.color.textPrimary
                            background: null
                        }
                    }
                }

                Item {
                    ScrollView {
                        anchors.fill: parent
                        TextArea {
                            readOnly: true
                            text: Facade.draftText
                            wrapMode: TextEdit.Wrap
                            color: Theme.tokens.color.textPrimary
                            background: null
                        }
                    }
                }

                ListView {
                    id: diffList
                    clip: true
                    spacing: 8
                    model: Facade.draftDiff
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        width: diffList.width
                        height: diffCard.implicitHeight
                        radius: Theme.tokens.radius.r12
                        color: Theme.tokens.color.bgSidebar
                        border.color: Theme.tokens.color.border
                        border.width: 1

                        ColumnLayout {
                            id: diffCard
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 6

                            Text {
                                text: root.diffLabel(kind)
                                font.pixelSize: 11
                                font.bold: true
                                color: root.diffTone(kind)
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: currentText !== ""
                                text: "当前：" + currentText
                                font.pixelSize: 12
                                color: Theme.tokens.color.textSecondary
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: draftText !== ""
                                text: "草稿：" + draftText
                                font.pixelSize: 12
                                color: Theme.tokens.color.textPrimary
                                wrapMode: Text.WordWrap
                            }
                            AppButton {
                                text: "段落级采用待接线"
                                enabled: false
                            }
                        }
                    }

                    EmptyState {
                        anchors.fill: parent
                        visible: Facade.draftDiff.count === 0
                        title: "无待处理差异"
                        body: "所有段落差异均已处理。"
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Item {
                    Layout.fillWidth: true
                }
                AppButton {
                    text: "放弃草稿"
                    onClicked: {
                        if (Facade.suggestions.count > 0) {
                            Facade.discardSuggestion(0)
                        }
                    }
                }
                AppButton {
                    text: "采用整章"
                    primary: true
                    onClicked: {
                        if (Facade.suggestions.count > 0) {
                            Facade.acceptSuggestion(0)
                        }
                    }
                }
            }
        }
    }

    function diffLabel(kind) {
        if (kind === "inserted") return "新增段落"
        if (kind === "deleted") return "删除段落"
        if (kind === "replaced") return "替换段落"
        return "未变"
    }

    function diffTone(kind) {
        if (kind === "inserted") return Theme.tokens.color.success
        if (kind === "deleted") return Theme.tokens.color.danger
        if (kind === "replaced") return Theme.tokens.color.warning
        return Theme.tokens.color.textSecondary
    }
}
