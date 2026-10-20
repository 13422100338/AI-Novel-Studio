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

    WriterInputReview {
        id: inputReview
        itemId: root.itemId
        canConfirm: root.state === "AWAITING_CONFIRMATION"
    }

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
                    : (root.state === "COMPLETED" || root.state === "ACCEPTED") ? Theme.tokens.color.success
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
                text: root.state === "COMPLETED" || root.state === "ACCEPTED" ? "✓" : "✎"
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
            visible: root.metadata.input_ready === true
            text: (root.metadata.scope === "SELECTION" ? "仅处理选文" : "当前章节候选")
                + " · 输入大纲 " + (root.metadata.outline_fingerprint || "").slice(0, 12)
                + " · 确认后固定"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
        Text {
            Layout.fillWidth: true
            text: "已收到 " + (root.metadata.word_count || 0) + " 字"
                + (root.metadata.target_words ? " · 目标约 " + root.metadata.target_words + " 字" : "")
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
            visible: root.state !== "AWAITING_CONFIRMATION"
        }
        Text {
            Layout.fillWidth: true
            text: root.state === "COMPLETED" ? "候选草稿已保留，等待你审阅。"
                : root.state === "ACCEPTED" ? "已写入正式正文并保留修订历史。"
                : root.state === "DISCARDED" ? "已放弃；原输入与检查点仍保留。"
                : root.detail
            textFormat: Text.PlainText
            font.pixelSize: 12
            color: root.state === "FAILED" ? Theme.tokens.color.danger : Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: root.metadata.adoption_note || ""
            textFormat: Text.PlainText
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
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
            visible: root.metadata.input_ready === true && (root.state === "AWAITING_CONFIRMATION" || root.metadata.run_id)
            AppButton {
                objectName: "writerInputReviewButton"
                text: root.state === "AWAITING_CONFIRMATION" ? "查看并确认输入" : "查看本次输入"
                onClicked: inputReview.showInput()
            }
            AppButton {
                text: "取消提案"
                ghost: true
                visible: root.state === "AWAITING_CONFIRMATION"
                enabled: !Facade.agentBusy
                onClicked: Facade.rejectWriterInput(root.itemId)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.busy || root.draftText !== ""
            AppButton {
                objectName: "writerCandidateViewButton"
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
        RowLayout {
            Layout.fillWidth: true
            visible: root.metadata.can_adopt === true || root.metadata.can_discard === true
            AppButton {
                objectName: "writerCandidateAdoptButton"
                text: root.metadata.partial === true ? "采用部分候选"
                    : root.metadata.scope === "SELECTION" ? "替换原选文" : "采用到本章"
                visible: root.metadata.can_adopt === true
                enabled: !Facade.agentBusy
                onClicked: Facade.adoptWriterDraft(root.itemId, root.metadata.partial === true)
            }
            AppButton {
                objectName: "writerCandidateDiscardButton"
                text: "放弃候选"
                ghost: true
                visible: root.metadata.can_discard === true
                enabled: !Facade.agentBusy
                onClicked: Facade.discardWriterDraft(root.itemId)
            }
        }
    }
}
