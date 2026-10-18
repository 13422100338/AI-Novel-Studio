import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.ScrollBar {
    id: root

    policy: Basic.ScrollBar.AsNeeded
    implicitWidth: 10
    active: hovered || pressed

    background: Rectangle {
        color: "transparent"
    }

    contentItem: Rectangle {
        implicitWidth: 6
        radius: 3
        color: Theme.tokens.color.accent
        opacity: root.active ? 0.9 : 0.45

        Behavior on opacity {
            NumberAnimation {
                duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.fast
                easing.type: Easing.OutCubic
            }
        }
    }
}
