import QtQuick
import QtQuick.Layouts

// Mock change-set proposal card (C1.1): shows a proposed project mutation and
// offers confirm/edit/discard. Nothing is applied to a real project in C1.
AgentCard {
    id: root
    objectName: "changeSetCard"

    property string itemId: ""
    property string label: ""
    property string target: ""
    property string operation: ""
    property string beforeText: ""
    property string afterText: ""
    property string risk: ""
    property string reason: ""
    property string state: ""
    signal approve()
    signal edit()
    signal discard()

    readonly property bool settled:
        state === "APPLIED" || state === "DISCARDED" || state === "CANCELLED"

    cardTitle: "变更提案 · " + root.operation

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 8
        rowSpacing: 2

        Text {
            text: "对象"
            font.pixelSize: 10
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.target
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textPrimary
        }
        Text {
            text: "修改前"
            font.pixelSize: 10
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.beforeText
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textPrimary
        }
        Text {
            text: "修改后"
            font.pixelSize: 10
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.afterText
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.warning
        }
        Text {
            text: "风险"
            font.pixelSize: 10
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.risk
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            color: root.risk === "高"
                ? Theme.tokens.color.danger
                : Theme.tokens.color.textPrimary
        }
        Text {
            text: "来源"
            font.pixelSize: 10
            color: Theme.tokens.color.textSecondary
        }
        Text {
            Layout.fillWidth: true
            text: root.reason
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textPrimary
        }
    }

    Flow {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignRight
        spacing: 6

        AppButton {
            text: "放弃"
            enabled: !root.settled
            onClicked: root.discard()
        }
        AppButton {
            text: "编辑"
            enabled: !root.settled
            onClicked: root.edit()
        }
        AppButton {
            text: "确认"
            primary: true
            enabled: !root.settled
            onClicked: root.approve()
        }
    }
}
