import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Dialog {
    id: root
    property string itemId: ""
    property var preview: ({})
    property bool canConfirm: false
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(820, parent ? parent.width - 48 : 820)
    height: Math.min(760, parent ? parent.height - 48 : 760)
    padding: 20
    modal: true
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 16 }

    function showInput() {
        const value = Facade.writerInputPreview(itemId)
        if (!value.messages || value.messages.length === 0) return
        preview = value
        const outlineIndex = value.messages.findIndex(function(item) { return item.content.indexOf("[FULL_OUTLINE;") === 0 })
        choices.currentIndex = Math.max(0, outlineIndex)
        open()
    }

    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text { text: "正文模型输入"; font.pixelSize: 21; font.bold: true; color: Theme.tokens.color.textPrimary }
            Item { Layout.fillWidth: true }
            AppButton { text: "关闭"; ghost: true; onClicked: root.close() }
        }
        Text {
            Layout.fillWidth: true
            text: "范围：" + (root.preview.scope === "SELECTION" ? "仅处理选文" : "当前章节候选")
                + " · 模型：" + (root.preview.model || "")
                + "\n输入保守估算 " + Number(root.preview.estimated_tokens || 0).toLocaleString(Qt.locale(), "f", 0)
                + " / 容量 " + Number(root.preview.context_window || 0).toLocaleString(Qt.locale(), "f", 0) + " tokens"
                + "\n笔记：" + ((root.preview.note_mode || "NONE") === "NONE" ? "不附笔记"
                    : root.preview.note_mode === "FULL" ? "所选原文 · " + (root.preview.note_refs || []).length + " 篇"
                    : "Codex 整理要点 · 来源 " + (root.preview.note_refs || []).length + " 篇")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 13
        }
        Text {
            Layout.fillWidth: true
            text: "以下是实际发送的完整消息。切换消息检查原文；大纲、章要求、正文或模型变化时需重新确认。"
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 12
        }
        ComboBox {
            id: choices
            objectName: "writerInputMessageChoice"
            Layout.fillWidth: true
            model: (root.preview.messages || []).map(function(item, index) { return (index + 1) + ". " + item.role + " · " + item.content.split("\n")[0].slice(0, 100) })
            palette.text: Theme.tokens.color.textPrimary
            background: Rectangle { color: Theme.tokens.color.bgCanvas; border.color: Theme.tokens.color.border; radius: 8 }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            background: Rectangle { color: Theme.tokens.color.bgCanvas; border.color: Theme.tokens.color.border; radius: 8 }
            TextArea {
                objectName: "writerInputMessageText"
                text: root.preview.messages && choices.currentIndex >= 0 && choices.currentIndex < root.preview.messages.length
                    ? root.preview.messages[choices.currentIndex].content : ""
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.tokens.color.textPrimary
                font.pixelSize: 14
                padding: 14
                background: null
            }
        }
        Text {
            Layout.fillWidth: true
            text: "需要修改输入时，关闭后在聊天中说明要求或重新指定参考章节。生成的候选不会覆盖正式稿。"
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AppButton { text: "返回"; onClicked: root.close() }
            AppButton {
                objectName: "writerInputConfirmButton"
                text: "确认输入并生成"
                primary: true
                visible: root.canConfirm
                enabled: !Facade.agentBusy
                onClicked: { if (Facade.confirmWriterInput(root.itemId)) root.close() }
            }
        }
    }
}
