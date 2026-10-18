import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: root
    implicitHeight: 36
    implicitWidth: 180
    leftPadding: 12
    rightPadding: 30
    font.pixelSize: 13
    activeFocusOnTab: true
    contentItem: Text {
        text: root.displayText
        font: root.font
        color: root.enabled ? Theme.tokens.color.textPrimary : Theme.tokens.color.textSecondary
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Text {
        x: root.width - width - 12
        y: (root.height - height) / 2
        text: "⌄"
        font.pixelSize: 16
        color: Theme.tokens.color.textSecondary
    }
    background: Rectangle {
        radius: Theme.tokens.radius.r8
        color: root.enabled ? Theme.tokens.color.bgEditor : Theme.tokens.color.bgSidebar
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
    }
    delegate: ItemDelegate {
        required property int index
        width: root.popup.width - 8
        implicitHeight: 36
        highlighted: root.highlightedIndex === index
        contentItem: Text {
            text: root.textAt(index)
            font: root.font
            color: Theme.tokens.color.textPrimary
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 6
            color: parent.highlighted ? Theme.tokens.color.hover : "transparent"
        }
    }
    popup: Popup {
        y: root.height + 4
        width: root.width
        padding: 4
        implicitHeight: Math.min(292, menu.contentHeight + 8)
        contentItem: ListView {
            id: menu
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: ScrollBar {}
        }
        background: Rectangle {
            radius: Theme.tokens.radius.r8
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
        }
    }
}
