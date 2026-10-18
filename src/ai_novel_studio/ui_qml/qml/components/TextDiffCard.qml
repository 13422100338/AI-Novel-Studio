import QtQuick
import QtQuick.Layouts

AgentCard {
    id: root
    objectName: "textDiffCard"

    property string itemId: ""
    property string state: ""
    property string label: ""
    property string currentText: ""
    property string draftText: ""
    signal approve()
    signal retry()
    signal discard()

    readonly property bool settled:
        state === "APPLIED" || state === "DISCARDED" || state === "CANCELLED"

    cardTitle: root.label

    Text {
        Layout.fillWidth: true
        text: "当前：" + root.currentText
        font.pixelSize: 11
        color: Theme.tokens.color.textSecondary
        wrapMode: Text.WordWrap
    }
    Text {
        Layout.fillWidth: true
        text: "修改：" + root.draftText
        font.pixelSize: 11
        color: Theme.tokens.color.warning
        wrapMode: Text.WordWrap
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
            text: "再次修改"
            enabled: !root.settled
            onClicked: root.retry()
        }
        AppButton {
            text: "确认替换"
            primary: true
            enabled: !root.settled
            onClicked: root.approve()
        }
    }
}
