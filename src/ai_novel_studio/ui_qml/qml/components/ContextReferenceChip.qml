import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property string label: ""
    property string preview: ""
    signal cleared()

    // Public sizing rule: the chip spans its host's width. Without this a
    // Rectangle has no implicitWidth (0), the inner RowLayout collapses and
    // the label/preview/close children all stack at x=0 and overlap.
    implicitWidth: parent ? parent.width : 320
    implicitHeight: content.implicitHeight + 14
    radius: Theme.tokens.radius.r8
    color: Theme.tokens.color.bgSidebar
    border.color: Theme.tokens.color.accent
    border.width: 1

    // Prevent a jarring pop-in: the chip fades in/out when a selection
    // reference appears or is cleared. Occasional frequency, ease-out.
    Behavior on opacity {
        NumberAnimation {
            duration: Facade.reduceMotion ? 0 : 150
            easing.type: Easing.OutCubic
        }
    }

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 7
        spacing: 3

        RowLayout {
            Layout.fillWidth: true
            Text {
                objectName: "selectionQuoteLabel"
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: "引用选文 · " + root.label
                font.pixelSize: 11
                elide: Text.ElideRight
                maximumLineCount: 1
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "clearSelectionButton"
                text: "×"
                implicitWidth: 24
                implicitHeight: 20
                onClicked: root.cleared()
            }
        }
        Text {
            objectName: "selectionQuotePreview"
            textFormat: Text.PlainText
            Layout.fillWidth: true
            visible: root.preview !== ""
            text: root.preview
            font.pixelSize: 12
            wrapMode: Text.Wrap
            elide: Text.ElideRight
            maximumLineCount: 2
            color: Theme.tokens.color.textSecondary
        }
    }
}
