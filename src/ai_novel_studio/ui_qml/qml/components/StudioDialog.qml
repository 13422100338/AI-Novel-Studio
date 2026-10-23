import QtQuick
import QtQuick.Controls.Basic

Dialog {
    id: root
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent ? parent.width - 40 : 480)
    padding: 22
    modal: true
    focus: true
    standardButtons: Dialog.NoButton
    background: Rectangle {
        color: Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        radius: 18
    }
    header: Text {
        text: root.title
        textFormat: Text.PlainText
        color: Theme.tokens.color.textPrimary
        font.pixelSize: 20
        font.bold: true
        padding: 22
        bottomPadding: 4
    }
    Overlay.modal: Rectangle {
        color: "#44000000"
    }
}
