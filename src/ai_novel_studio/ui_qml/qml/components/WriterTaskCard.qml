import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "writerTaskCard"
    property string itemId: ""
    property string label: "正文生成"
    property string state: "PREPARING"
    property string detail: ""
    property string draftText: ""
    property string payloadJson: "{}"
    property bool busy: false
    property bool expanded: false
    readonly property var metadata: {
        try { return JSON.parse(payloadJson) } catch (e) { return {} }
    }
    signal stopRequested()
    signal copyRequested()

    width: parent ? parent.width : 320
    implicitHeight: content.implicitHeight + 32
    radius: 14
    color: Theme.tokens.color.bgEditor
    border.color: Theme.tokens.color.border
    border.width: 1

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Rectangle {
                width: 9; height: 9; radius: 4.5
                color: root.state === "FAILED" ? Theme.tokens.color.danger
                    : root.state === "COMPLETED" ? Theme.tokens.color.success
                    : Theme.tokens.color.accent
            }
            Text {
                Layout.fillWidth: true
                text: root.label
                textFormat: Text.PlainText
                font.pixelSize: 15
                font.bold: true
                color: Theme.tokens.color.textPrimary
                wrapMode: Text.WordWrap
            }
            Text {
                text: root.state === "COMPLETED" ? "✓" : "✎"
                font.pixelSize: 18
                color: Theme.tokens.color.accent
            }
        }
        Text {
            Layout.fillWidth: true
            text: root.metadata.model || "独立写作模型"
            textFormat: Text.PlainText
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
        Rectangle {
            Layout.fillWidth: true
            height: 3
            radius: 1.5
            color: Theme.tokens.color.hover
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: root.state === "COMPLETED" ? Theme.tokens.color.success : Theme.tokens.color.accent
                opacity: root.busy ? 0.65 : 0.3
                SequentialAnimation on opacity {
                    running: root.busy && !Facade.reduceMotion
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 650 }
                    NumberAnimation { to: 0.8; duration: 650 }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: "已收到 " + (root.metadata.word_count || 0) + " 字"
                + (root.metadata.target_words ? " · 目标约 " + root.metadata.target_words + " 字" : "")
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.state === "COMPLETED" ? "候选草稿已保留，等待你审阅。" : root.detail
            textFormat: Text.PlainText
            font.pixelSize: 12
            color: root.state === "FAILED" ? Theme.tokens.color.danger : Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            visible: root.expanded && root.draftText !== ""
            clip: true
            TextArea {
                text: root.draftText
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font.family: Theme.tokens.font.manuscript
                font.pixelSize: 15
                color: Theme.tokens.color.textPrimary
                background: null
                padding: 0
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.busy || root.draftText !== ""
            AppButton {
                text: root.expanded ? "收起草稿" : "查看草稿"
                visible: root.draftText !== ""
                onClicked: root.expanded = !root.expanded
            }
            AppButton {
                text: "复制草稿"
                visible: root.draftText !== ""
                ghost: true
                onClicked: root.copyRequested()
            }
            Item { Layout.fillWidth: true }
            AppButton {
                text: "停止生成"
                visible: root.busy
                ghost: true
                onClicked: root.stopRequested()
            }
        }
    }
}
