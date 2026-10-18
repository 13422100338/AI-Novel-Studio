import QtQuick
import QtQuick.Controls

// Theme-styled tab button for TabBar (replaces the default gray Qt tab).
// Must remain a TabButton subclass so TabBar recognizes it as a tab
// (a plain Item delegate leaves TabBar.count at 0 and renders nothing).
// Matches AppButton language: r8 radius, bgSurface fill, hover/pressed
// feedback, accent underline + tint for the active tab. Colors come only
// from Theme tokens (design token rule).
TabButton {
    id: root

    implicitHeight: 34
    background: Rectangle {
        radius: Theme.tokens.radius.r8
        border.width: 1
        border.color: root.checked ? Theme.tokens.color.accent : Theme.tokens.color.border
        color: !root.enabled ? Theme.tokens.color.bgSidebar
             : root.checked ? Theme.tokens.color.hover
             : root.hovered ? Theme.tokens.color.bgSurface
             : "transparent"
        opacity: root.enabled ? 1.0 : 0.5

        Behavior on color {
            ColorAnimation {
                duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.fast
                easing.type: Easing.OutCubic
            }
        }

        // Active underline: the tab's "selected" affordance (accent, 2px).
        Rectangle {
            visible: root.checked
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            height: 2
            radius: 1
            color: Theme.tokens.color.accent
        }
    }

    // Replace the style's default contentItem so only our themed label is
    // rendered (the default TabButton contentItem otherwise overlaps and
    // renders at odd offsets inside the TabBar container).
    contentItem: Text {
        text: root.text
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: root.checked ? Theme.tokens.color.accent
             : Theme.tokens.color.textSecondary
    }
}
