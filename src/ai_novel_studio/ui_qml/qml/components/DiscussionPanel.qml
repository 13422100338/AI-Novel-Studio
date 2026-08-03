import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Plot-discussion chat panel that fills the AI reference drawer content.
// Frontend-isolated: replies are deterministic mocks until the backend
// discussion port is wired.
Item {
    id: root

    property string title: "AI 参考 · 剧情商讨"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Text {
            Layout.fillWidth: true
            text: root.title
            font.pixelSize: 15
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        ListView {
            id: messageList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: Facade.discussionMessages
            ScrollBar.vertical: ScrollBar {}

            delegate: Rectangle {
                width: messageList.width
                height: bubble.implicitHeight + 14
                radius: Theme.tokens.radius.r12
                color: role === "user"
                    ? Theme.tokens.color.accent
                    : Theme.tokens.color.bgSidebar
                border.color: Theme.tokens.color.border
                border.width: role === "user" ? 0 : 1

                Text {
                    id: bubble
                    anchors.fill: parent
                    anchors.margins: 8
                    text: model.text
                    font.pixelSize: 12
                    color: role === "user"
                        ? "white"
                        : Theme.tokens.color.textPrimary
                    wrapMode: Text.WordWrap
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: Facade.discussionMessages.count === 0
                title: "剧情商讨"
                body: "就当前章节向 AI 商讨剧情走向、人物动机或伏笔；回复为 Mock，模型接线后启用真实讨论。"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            TextField {
                id: input
                objectName: "discussionInput"
                Layout.fillWidth: true
                placeholderText: "例如：让林默在钟楼里发现什么？"
                color: Theme.tokens.color.textPrimary
                placeholderTextColor: Theme.tokens.color.textSecondary
                background: Rectangle {
                    color: Theme.tokens.color.bgSurface
                    border.color: Theme.tokens.color.border
                    border.width: 1
                    radius: Theme.tokens.radius.r8
                }
                onAccepted: root.send()
            }

            AppButton {
                objectName: "discussionSendButton"
                text: "发送"
                primary: true
                enabled: input.text.trim() !== "" && !Facade.discussionBusy
                onClicked: root.send()
            }
        }

        AppButton {
            objectName: "discussionClearButton"
            text: "清空对话"
            visible: Facade.discussionMessages.count > 0
            onClicked: Facade.clearDiscussion()
        }
    }

    function send() {
        const text = input.text.trim()
        if (text === "") {
            return
        }
        Facade.sendDiscussion(text)
        input.text = ""
    }
}
