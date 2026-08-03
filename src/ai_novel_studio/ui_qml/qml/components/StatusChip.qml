import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property string label: ""
    property string value: ""
    property string tone: "neutral"
    property string tooltipText: ""
    property color toneColor: root.tone === "success" ? Theme.tokens.color.success
                              : root.tone === "warning" ? Theme.tokens.color.warning
                              : root.tone === "danger" ? Theme.tokens.color.danger
                              : root.tone === "accent" ? Theme.tokens.color.accent
                              : Theme.tokens.color.textSecondary

    implicitHeight: 24
    implicitWidth: content.implicitWidth + 16
    radius: Theme.tokens.radius.r8
    color: Theme.tokens.color.bgSurface
    border.color: Theme.tokens.color.border
    border.width: 1

    ToolTip.visible: hoverArea.containsMouse && root.tooltipText !== ""
    ToolTip.text: root.tooltipText
    ToolTip.delay: 300

    MouseArea {
        id: hoverArea
        anchors.fill: parent
        hoverEnabled: true
    }

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 6

        Rectangle {
            width: 6
            height: 6
            radius: 3
            visible: root.label !== ""
            color: root.toneColor
        }
        Text {
            text: root.label
            font.pixelSize: 11
            color: Theme.tokens.color.textSecondary
        }
        Text {
            text: root.value
            font.pixelSize: 11
            color: Theme.tokens.color.textPrimary
        }
    }
}
