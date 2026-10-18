import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: root
    implicitHeight: 36
    leftPadding: 12
    rightPadding: 12
    font.pixelSize: 13
    color: Theme.tokens.color.textPrimary
    placeholderTextColor: Theme.tokens.color.textSecondary
    selectionColor: Theme.tokens.color.accent
    selectedTextColor: "white"
    activeFocusOnTab: true
    background: Rectangle {
        radius: Theme.tokens.radius.r8
        color: root.enabled ? Theme.tokens.color.bgEditor : Theme.tokens.color.bgSidebar
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
    }
}
