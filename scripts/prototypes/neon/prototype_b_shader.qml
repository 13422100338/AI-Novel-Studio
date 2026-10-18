import QtQuick
import QtQuick.Layouts

// Prototype B window: the formal candidate (NeonRoundedBorderEffect) on one
// 320x160 rounded card, with state buttons and DPR readout. Prototype-only;
// never referenced by the production UI.
Window {
    id: root
    objectName: "prototypeBWindow"
    width: 560
    height: 420
    visible: true
    color: "#202124"
    title: "Prototype B · ShaderEffect + qsb neon border"

    property string mode: "thinking"
    property bool reduceMotion: false
    property bool safeTier: false

    readonly property color modeColor: {
        var map = {
            "thinking": "#8AB4F8",
            "generating": "#8AB4F8",
            "success": "#81C995",
            "error": "#F28B82",
            "cancelled": "#9A958C",
            "idle": "#8AB4F8"
        }
        return map[root.mode] || "#8AB4F8"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Item {
            id: cardSlot
            Layout.preferredWidth: 320
            Layout.preferredHeight: 160
            Layout.alignment: Qt.AlignHCenter

            Rectangle {
                anchors.fill: parent
                radius: 16
                color: "#292A2D"
            }
            NeonRoundedBorderEffect {
                id: neon
                objectName: "prototypeBNeon"
                anchors.fill: parent
                active: root.mode !== "idle"
                state: root.mode
                color: root.modeColor
                reduce: root.reduceMotion
                safeTier: root.safeTier
            }
            Text {
                anchors.centerIn: parent
                text: root.mode
                font.pixelSize: 13
                font.bold: true
                color: "#E8EAED"
            }
        }

        Flow {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            spacing: 6
            Repeater {
                model: ["thinking", "generating", "success", "error", "cancelled", "idle"]
                delegate: Rectangle {
                    width: 78
                    height: 28
                    radius: 8
                    color: root.mode === modelData ? "#3C4043" : "#292A2D"
                    border.color: "#3C4043"
                    border.width: 1
                    Text {
                        anchors.centerIn: parent
                        text: modelData
                        font.pixelSize: 11
                        color: "#E8EAED"
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.mode = modelData
                    }
                }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 10
            Text {
                text: "reduceMotion: " + (root.reduceMotion ? "开" : "关")
                font.pixelSize: 11
                color: "#AEB2B7"
            }
            MouseArea {
                width: 60
                height: 22
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: root.reduceMotion ? "#8AB4F8" : "#3C4043"
                }
                onClicked: root.reduceMotion = !root.reduceMotion
            }
            Text {
                text: "safe: " + (root.safeTier ? "开" : "关")
                font.pixelSize: 11
                color: "#AEB2B7"
            }
            MouseArea {
                width: 60
                height: 22
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: root.safeTier ? "#F28B82" : "#3C4043"
                }
                onClicked: root.safeTier = !root.safeTier
            }
            Text {
                text: "DPR " + root.devicePixelRatio.toFixed(2)
                    + " · shader " + neon.shaderStatus
                font.pixelSize: 11
                color: neon.shaderReady ? "#81C995" : "#F28B82"
            }
            Text {
                text: "status=" + neon.shaderStatus
                    + " ready=" + neon.shaderReady
                    + " log=" + JSON.stringify(neon.shaderLog)
                font.pixelSize: 11
                color: "#AEB2B7"
            }
        }
    }

}
