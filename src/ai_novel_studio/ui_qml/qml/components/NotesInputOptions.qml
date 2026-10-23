import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    readonly property var notes: Facade.notes
    spacing: 7
    Text {
        text: "本次正文输入 · 已选 " + root.notes.state.selectedIds.length + " 篇笔记"
        color: Theme.tokens.color.textSecondary
        font.pixelSize: 12
    }
    AppComboBox {
        objectName: "noteInputMode"
        Layout.fillWidth: true
        model: [{value: "NONE", label: "不附笔记"}, {value: "FULL", label: "附所选笔记原文"}, {value: "SUMMARY", label: "让 Codex 整理所选笔记要点"}]
        textRole: "label"
        valueRole: "value"
        currentIndex: ["NONE", "FULL", "SUMMARY"].indexOf(root.notes.state.mode)
        enabled: root.notes.state.available && !Facade.agentBusy
        onActivated: root.notes.setMode(currentValue)
    }
}
