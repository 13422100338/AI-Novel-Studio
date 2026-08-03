import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    z: 100

    property bool open: false
    property int drawerWidth: 340
    property bool webEngineMode: false
    property bool dock: false
    signal closed()

    anchors.fill: parent

    Rectangle {
        id: dim
        anchors.fill: parent
        color: "#80000000"
        opacity: root.dock || !root.open ? 0 : 1
        visible: !root.dock && root.open

        Behavior on opacity {
            NumberAnimation { duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.fast }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.closed()
        }
    }

    Rectangle {
        id: panel
        objectName: "aiDrawer"
        width: root.dock ? parent.width : root.drawerWidth
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        x: root.dock ? 0 : (root.open ? 0 : root.drawerWidth)
        color: Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        border.width: 1
        clip: true

        Behavior on x {
            NumberAnimation { duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.panel }
        }

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
                    objectName: "drawerCloseButton"
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
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        ScrollView {
                            anchors.fill: parent
                            TextArea {
                                objectName: "draftBaseViewer"
                                readOnly: true
                                text: Facade.draftBaseText
                                wrapMode: TextEdit.Wrap
                                color: Theme.tokens.color.textPrimary
                                background: null
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        ScrollView {
                            anchors.fill: parent
                            TextArea {
                                objectName: "draftTextViewer"
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
                        objectName: "diffList"
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
                                TextArea {
                                    id: editArea
                                    objectName: "diffEditArea"
                                    Layout.fillWidth: true
                                    visible: kind === "replaced" || kind === "inserted"
                                    text: draftText
                                    placeholderText: "编辑后采用"
                                    wrapMode: TextEdit.Wrap
                                    color: Theme.tokens.color.textPrimary
                                    placeholderTextColor: Theme.tokens.color.textSecondary
                                    background: null
                                    implicitHeight: 56
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    AppButton {
                                        objectName: "rejectDiffButton"
                                        text: "忽略此段"
                                        visible: kind !== "unchanged" && !root.webEngineMode
                                        onClicked: Facade.rejectDiffBlock(blockId)
                                    }
                                    AppButton {
                                        objectName: "acceptDiffButton"
                                        text: "采用此段"
                                        primary: true
                                        visible: kind !== "unchanged" && !root.webEngineMode
                                        onClicked: Facade.acceptDiffBlock(blockId)
                                    }
                                    AppButton {
                                        objectName: "editAcceptDiffButton"
                                        text: "编辑后采用"
                                        visible: (kind === "replaced" || kind === "inserted") && !root.webEngineMode
                                        onClicked: Facade.editAndAcceptDiffBlock(blockId, editArea.text)
                                    }
                                    AppButton {
                                        objectName: "webEngineDiffHint"
                                        text: "段落级采用待接线"
                                        visible: root.webEngineMode && (kind === "replaced" || kind === "inserted")
                                        enabled: false
                                    }
                                }
                            }
                        }

                        EmptyState {
                            anchors.fill: parent
                            visible: Facade.draftDiff.count === 0
                            title: "无待处理差异"
                            body: "所有段落差异均已处理；保存正文后差异将随编辑保留。"
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
                        objectName: "discardDraftButton"
                        text: "放弃草稿"
                        onClicked: {
                            var row = Facade.suggestions.count > 0 ? 0 : -1
                            if (row >= 0) {
                                Facade.discardSuggestion(row)
                            }
                        }
                    }
                    AppButton {
                        objectName: "acceptDraftButton"
                        text: "采用整章"
                        primary: true
                        onClicked: {
                            var row = Facade.suggestions.count > 0 ? 0 : -1
                            if (row >= 0) {
                                Facade.acceptSuggestion(row)
                            }
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
