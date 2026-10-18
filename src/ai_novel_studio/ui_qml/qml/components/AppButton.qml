import QtQuick
import QtQuick.Controls.Basic

Button {
    id: root

    property bool primary: false
    property bool selected: false
    // Ghost tier (Visual V0): transparent body, accent text, border only on
    // hover. Used for low-emphasis inline actions.
    property bool ghost: false
    property int radius: Theme.tokens.radius.r8
    implicitHeight: 36
    implicitWidth: label.implicitWidth + 24
    leftPadding: 12
    rightPadding: 12
    activeFocusOnTab: true
    font.pixelSize: 13
    background: Rectangle {
        radius: root.radius
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? Theme.tokens.color.accent : root.ghost ? "transparent" : Theme.tokens.color.border
        color: !root.enabled ? Theme.tokens.color.bgSidebar : root.selected || root.primary ? Theme.tokens.color.accent : root.hovered ? Theme.tokens.color.hover : root.ghost ? "transparent" : Theme.tokens.color.bgSurface
    }
    opacity: root.enabled ? 1.0 : 0.5
    // Press feedback: respond on pointer-down, subtle and near-imperceptible
    // (Tens/day frequency tier). Ease-out starts fast so the press feels
    // immediate, not delayed.
    scale: root.pressed && !root.activeFocus ? 0.98 : 1.0

    Behavior on scale {
        NumberAnimation {
            duration: Facade.reduceMotion ? 0 : 120
            easing.type: Easing.OutCubic
        }
    }

    contentItem: Text {
        id: label
        text: root.text
        font: root.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        color: root.primary || root.selected ? "white" : root.ghost ? Theme.tokens.color.accent : Theme.tokens.color.textPrimary
    }
}
