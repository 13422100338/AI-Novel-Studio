import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property bool details: false
    property bool compact: false
    property bool showModelControls: true
    readonly property bool available: typeof CodexSettings !== "undefined" && CodexSettings !== null
    readonly property string effortDisplay: {
        if (!available || CodexSettings.effortIndex < 0) return ""
        const value = CodexSettings.efforts[CodexSettings.effortIndex].value
        const labels = {none:"None", minimal:"Minimal", low:"Low", medium:"Medium", high:"High", xhigh:"Extra High", max:"Max", ultra:"Ultra"}
        return labels[value] || value
    }
    spacing: 8
    GridLayout {
        visible: root.showModelControls
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 8
        rowSpacing: 6
        Text {
            visible: !root.compact
            Layout.fillWidth: true
            text: "模型"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        Text {
            visible: !root.compact
            text: "思考强度"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        CodexChoiceBox {
            id: modelChoice
            objectName: root.compact ? "composerCodexModelCombo" : "codexModelCombo"
            compact: root.compact
            popupAbove: root.compact
            menuTitle: "选择模型"
            secondaryText: root.compact ? root.effortDisplay : ""
            extraFooter: root.compact ? effortFooter : null
            Layout.fillWidth: true
            Layout.minimumWidth: 100
            textRole: "label"
            valueRole: "value"
            model: root.available ? CodexSettings.models : []
            currentIndex: root.available ? CodexSettings.modelIndex : -1
            displayText: currentIndex < 0 ? "选择模型" : currentText
            enabled: root.available && CodexSettings.ready && !CodexSettings.busy && !Facade.agentBusy
            onActivated: CodexSettings.selectModel(currentValue)
        }
        CodexChoiceBox {
            objectName: "codexEffortCombo"
            visible: !root.compact
            menuTitle: "思考强度"
            Layout.preferredWidth: root.compact ? 74 : 94
            textRole: "label"
            valueRole: "value"
            model: root.available ? CodexSettings.efforts : []
            currentIndex: root.available ? CodexSettings.effortIndex : -1
            displayText: currentIndex < 0 ? "强度" : currentText
            enabled: root.available && CodexSettings.ready && !CodexSettings.busy && !Facade.agentBusy
            onActivated: CodexSettings.selectEffort(currentValue)
        }
    }
    RowLayout {
        visible: !root.compact
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
        visible: !root.compact && (root.details || (root.available && (!CodexSettings.ready || CodexSettings.busy)))
        Layout.fillWidth: true
        text: root.available ? (root.details ? CodexSettings.quotaText + "\n" + CodexSettings.contextText + "\n" : "") + CodexSettings.statusText : ""
        wrapMode: Text.WordWrap
        color: Theme.tokens.color.textSecondary
        font.pixelSize: 12
    }
    Component {
        id: effortFooter
        ColumnLayout {
            spacing: 8
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.tokens.color.border }
            Text { text: "思考强度"; color: Theme.tokens.color.textSecondary; font.pixelSize: 12 }
            Flow {
                id: effortChoices
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: root.available ? CodexSettings.efforts : []
                    AppButton {
                        required property var modelData
                        required property int index
                        objectName: "composerCodexEffortChoice-" + index
                        text: modelData.label
                        width: Math.min(implicitWidth, effortChoices.width)
                        implicitHeight: 28
                        font.pixelSize: 12
                        selected: index === CodexSettings.effortIndex
                        enabled: !Facade.agentBusy
                        contentItem: Text {
                            text: parent.text
                            textFormat: Text.PlainText
                            font: parent.font
                            elide: Text.ElideRight
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: parent.selected ? "white" : Theme.tokens.color.textPrimary
                        }
                        onClicked: { CodexSettings.selectEffort(modelData.value); modelChoice.popup.close() }
                    }
                }
            }
        }
    }
    function ensureCatalog() {
        if (root.visible && root.available && typeof Facade !== "undefined" && Facade.codexEnabled && !CodexSettings.ready && !CodexSettings.busy)
            CodexSettings.refresh();
    }
    function openModels() { modelChoice.forceActiveFocus(); modelChoice.popup.open() }
    Component.onCompleted: ensureCatalog()
    onVisibleChanged: ensureCatalog()
}
