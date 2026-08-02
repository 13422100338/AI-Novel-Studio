import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property bool open: false
    property int drawerWidth: 340
    signal closed()

    anchors.fill: parent

    Rectangle {
        id: dim
        anchors.fill: parent
        color: "#80000000"
        opacity: root.open ? 1 : 0
        visible: root.open

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
        width: root.drawerWidth
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        x: root.open ? 0 : root.drawerWidth
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
        }
    }
}
