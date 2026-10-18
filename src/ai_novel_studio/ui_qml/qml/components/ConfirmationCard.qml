import QtQuick
import QtQuick.Layouts

AgentCard {
    id: root
    objectName: "confirmationCard"

    property string itemId: ""
    property string state: ""
    property string label: ""
    property string text: ""
    signal confirm()
    signal cancel()

    readonly property bool settled:
        state === "APPLIED" || state === "DISCARDED" || state === "CANCELLED"

    cardTitle: root.label

    Text {
        Layout.fillWidth: true
        text: root.text
        font.pixelSize: 11
        color: Theme.tokens.color.textSecondary
        wrapMode: Text.WordWrap
    }
    Flow {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignRight
        spacing: 6

        AppButton {
            text: "取消"
            enabled: !root.settled
            onClicked: root.cancel()
        }
        AppButton {
            text: "确认"
            primary: true
            enabled: !root.settled
            onClicked: root.confirm()
        }
    }
}
