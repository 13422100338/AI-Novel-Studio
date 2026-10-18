import QtQuick

Rectangle {
    id: root
    objectName: "agentTextBlock"

    property string text: ""
    property bool user: false
    property bool markdown: !root.user
    property color textColor: root.user
        ? "white"
        : Theme.tokens.color.textPrimary

    implicitHeight: Math.max(32, body.implicitHeight + 20)
    width: parent ? parent.width : 320
    radius: Theme.tokens.radius.r12
    color: root.user ? Theme.tokens.color.accent : Theme.tokens.color.bgSidebar
    border.color: Theme.tokens.color.border
    border.width: root.user ? 0 : 1

    TextEdit {
        id: body
        objectName: "agentMessageBody"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        text: typeof ChatMarkup !== "undefined"
            ? (root.markdown ? ChatMarkup.render(root.text) : ChatMarkup.literal(root.text))
            : root.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>")
        // Keep the document format stable: Qt rewrites `text` when switching
        // between formats, which can replace a user's literal input with HTML.
        textFormat: TextEdit.RichText
        readOnly: true
        selectByMouse: true
        font.pixelSize: 14
        wrapMode: TextEdit.Wrap
        color: root.textColor
    }
}
