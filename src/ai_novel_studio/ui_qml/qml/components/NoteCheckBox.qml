import QtQuick
import QtQuick.Controls.Basic

CheckBox {
    id: control
    spacing: 8
    padding: 3
    font.pixelSize: 13
    implicitHeight: Math.max(30, contentItem.implicitHeight + 6)
    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 5
        color: control.checked ? Theme.tokens.color.accent : Theme.tokens.color.bgCanvas
        border.color: control.checked || control.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
        border.width: control.activeFocus ? 2 : 1
        opacity: control.enabled ? 1 : 0.55
        Text { anchors.centerIn: parent; text: control.checked ? "✓" : ""; color: "white"; font.pixelSize: 13; font.bold: true }
    }
    contentItem: Text {
        text: control.text
        font: control.font
        leftPadding: control.indicator.width + control.spacing
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        color: control.enabled ? Theme.tokens.color.textPrimary : Theme.tokens.color.textSecondary
    }
}
