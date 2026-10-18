import QtQuick
import QtQuick.Layouts
import "../effects"

// run_status timeline card. Carries the production neon border (prototype B
// shader): busy runs the thinking loop, DONE sweeps success once, anything
// else keeps the static state border. The flow layer never participates in
// layout, so the C1.3 geometry rules (height from content, delegate width)
// stay intact.
Item {
    id: root
    objectName: "agentRunStatus"

    property string label: ""
    property bool busy: false
    property string status: ""

    width: parent ? parent.width : 320
    implicitHeight: Math.max(28, bodyRow.implicitHeight + 16)

    readonly property string neonState: {
        if (!root.busy && root.status === "DONE") {
            return "success"
        }
        if (root.busy) {
            return "thinking"
        }
        return "idle"
    }

    Rectangle {
        id: body
        anchors.fill: parent
        radius: Theme.tokens.radius.r12
        color: Theme.tokens.color.bgSidebar
        border.color: Theme.tokens.color.border
        border.width: 1

        RowLayout {
            id: bodyRow
            anchors.fill: parent
            anchors.margins: 8
            spacing: 6

            Rectangle {
                width: 8
                height: 8
                radius: 4
                color: root.busy
                    ? Theme.tokens.color.accent
                    : Theme.tokens.color.success
            }
            Text {
                Layout.fillWidth: true
                text: root.busy ? root.label + "\u2026" : root.label
                font.pixelSize: 11
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.textSecondary
            }
            Text {
                text: root.status
                font.pixelSize: 10
                color: Theme.tokens.color.textSecondary
            }
        }
    }

    StreamingGlowBorder {
        objectName: "agentRunStatusNeon"
        anchors.fill: parent
        radius: Theme.tokens.radius.r12
        active: root.neonState !== "idle"
        state: root.neonState
    }
}
