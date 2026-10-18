import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property bool details: false
    readonly property bool available: typeof CodexSettings !== "undefined" && CodexSettings !== null
    spacing: 8
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 8
        rowSpacing: 6
        Text {
            Layout.fillWidth: true
            text: "模型"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        Text {
            text: "思考强度"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        AppComboBox {
            objectName: "codexModelCombo"
            Layout.fillWidth: true
            Layout.minimumWidth: 100
            textRole: "label"
            valueRole: "value"
            model: root.available ? CodexSettings.models : []
            currentIndex: root.available ? CodexSettings.modelIndex : -1
            enabled: root.available && CodexSettings.ready && !CodexSettings.busy && !Facade.agentBusy
            onActivated: CodexSettings.selectModel(currentValue)
        }
        AppComboBox {
            objectName: "codexEffortCombo"
            Layout.preferredWidth: 94
            textRole: "label"
            valueRole: "value"
            model: root.available ? CodexSettings.efforts : []
            currentIndex: root.available ? CodexSettings.effortIndex : -1
            enabled: root.available && CodexSettings.ready && !CodexSettings.busy && !Facade.agentBusy
            onActivated: CodexSettings.selectEffort(currentValue)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        CheckBox {
            objectName: "codexWebSearchCheck"
            text: "联网查资料"
            font.pixelSize: 12
            checked: root.available && CodexSettings.webSearch
            enabled: root.available && CodexSettings.ready && !Facade.agentBusy
            onClicked: CodexSettings.setWebSearch(checked)
        }
        Text {
            Layout.fillWidth: true
            text: root.available ? CodexSettings.accountText : "Codex 设置待连接"
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 11
            elide: Text.ElideRight
        }
        AppButton {
            objectName: "codexRefreshButton"
            text: root.available && CodexSettings.busy ? "读取中" : "刷新"
            ghost: true
            enabled: root.available && !CodexSettings.busy
            onClicked: CodexSettings.refresh()
        }
    }
    Text {
        visible: root.details || (root.available && (!CodexSettings.ready || CodexSettings.busy))
        Layout.fillWidth: true
        text: root.available ? (root.details ? CodexSettings.quotaText + "\n" + CodexSettings.contextText + "\n" : "") + CodexSettings.statusText : ""
        wrapMode: Text.WordWrap
        color: Theme.tokens.color.textSecondary
        font.pixelSize: 12
    }
    function ensureCatalog() {
        if (root.visible && root.available && typeof Facade !== "undefined" && Facade.codexEnabled && !CodexSettings.ready && !CodexSettings.busy)
            CodexSettings.refresh();
    }
    Component.onCompleted: ensureCatalog()
    onVisibleChanged: ensureCatalog()
}
