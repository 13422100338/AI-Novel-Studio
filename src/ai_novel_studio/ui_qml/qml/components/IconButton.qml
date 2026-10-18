import QtQuick
import QtQuick

Rectangle {
    id: root

    property string iconText: ""
    // Vector icon kind (see NavIcon); when set it replaces the text glyph.
    property string iconKind: ""
    property string text: ""
    property bool selected: false
    signal clicked()

    implicitWidth: 44
    implicitHeight: 48
    radius: Theme.tokens.radius.r12
    // Flat modern selection: soft tinted body + accent icon/text + accent
    // edge bar, instead of a solid accent block.
    color: root.selected ? Theme.tokens.color.pressed
         : mouseArea.containsMouse ? Theme.tokens.color.hover : "transparent"
    // Same press feedback language as AppButton: instant on pointer-down,
    // near-imperceptible at the Tens/day navigation frequency.
    scale: mouseArea.pressed ? 0.97 : 1.0

    Behavior on color {
        ColorAnimation {
            duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.fast
            easing.type: Easing.OutCubic
        }
    }
    Behavior on scale {
        NumberAnimation {
            duration: Facade.reduceMotion ? 0 : 120
            easing.type: Easing.OutCubic
        }
    }

    Rectangle {
        width: 3
        height: 24
        radius: 2
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        visible: root.selected
        color: Theme.tokens.color.accent
    }

    Column {
        anchors.centerIn: parent
        spacing: 3
        // Every child centers itself horizontally: without this the icon
        // (narrower than the label) sticks to the column's left edge.
        NavIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.iconKind !== ""
            kind: root.iconKind
            iconColor: root.selected ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.iconKind === ""
            text: root.iconText
            font.pixelSize: 16
            color: root.selected ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.text
            font.pixelSize: 9
            color: root.selected ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.clicked()
    }
}
