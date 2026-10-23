import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    objectName: "outlineReferenceOverlay"
    required property var reader
    property var annotations: []
    property real columnX: 0
    property real columnWidth: 180
    property int layoutEpoch: 0
    property bool marginActive: true
    signal activated(string url)
    readonly property var lastGroup: {
        const epoch = layoutEpoch;
        return groups.count ? groups.itemAt(groups.count - 1) : null;
    }
    implicitHeight: marginActive && lastGroup ? lastGroup.y + lastGroup.height + 26 : 0

    Repeater {
        id: groups
        model: root.annotations
        onItemAdded: root.layoutEpoch++
        onItemRemoved: root.layoutEpoch++
        delegate: Item {
            id: group
            required property var modelData
            required property int index
            readonly property var anchorRect: {
                const text = root.reader.text;
                const contentHeight = root.reader.contentHeight;
                const width = root.reader.width;
                const textLength = root.reader.length;
                return textLength >= modelData.position ? root.reader.positionToRectangle(modelData.position) : Qt.rect(0, 0, 0, 0);
            }
            readonly property var previous: {
                const epoch = root.layoutEpoch;
                return index > 0 ? groups.itemAt(index - 1) : null;
            }
            x: root.columnX
            y: Math.max(anchorRect.y, previous ? previous.y + previous.height + 14 : 0)
            width: root.columnWidth
            height: references.implicitHeight

            ColumnLayout {
                id: references
                width: parent.width
                spacing: 8
                Repeater {
                    model: group.modelData.refs
                    AbstractButton {
                        id: referenceButton
                        required property var modelData
                        required property int index
                        readonly property point origin: {
                            const text = root.reader.text;
                            const textHeight = root.reader.contentHeight;
                            const localY = group.y + references.y + y;
                            if (root.reader.length < modelData.position)
                                return Qt.point(-12, 12);
                            const rect = root.reader.positionToRectangle(modelData.position);
                            return Qt.point(rect.x + 8 - group.x, rect.y + rect.height + 2 - localY);
                        }
                        objectName: (modelData.kind === "chapter" ? "outline-linked-" : "outline-note-") + modelData.id
                        Layout.fillWidth: true
                        implicitHeight: caption.implicitHeight + 8
                        padding: 4
                        enabled: modelData.available
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Link
                        Accessible.name: modelData.title
                        onClicked: root.activated(modelData.url)
                        Rectangle {
                            parent: referenceButton
                            x: referenceButton.origin.x
                            y: referenceButton.origin.y
                            width: Math.max(0, -12 - x)
                            height: 1
                            color: Theme.tokens.color.border
                        }
                        Rectangle {
                            parent: referenceButton
                            x: -12
                            y: Math.min(12, referenceButton.origin.y)
                            width: 1
                            height: Math.abs(12 - referenceButton.origin.y)
                            color: Theme.tokens.color.border
                        }
                        Rectangle {
                            parent: referenceButton
                            x: -12
                            y: 12
                            width: 12
                            height: 1
                            color: Theme.tokens.color.border
                        }
                        background: Rectangle {
                            radius: 6
                            color: parent.hovered || parent.activeFocus ? Theme.tokens.color.hover : "transparent"
                        }
                        contentItem: Column {
                            id: caption
                            spacing: 4
                            Text {
                                width: parent.width
                                text: "↗" + (referenceButton.index + 1) + " " + referenceButton.modelData.title
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                font.pixelSize: 12
                                font.underline: true
                                color: referenceButton.enabled ? Theme.tokens.color.accent : Theme.tokens.color.textSecondary
                            }
                            Text {
                                width: parent.width
                                text: (referenceButton.modelData.kind === "chapter" ? "章节 · " : "笔记 · ") + referenceButton.modelData.status
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                font.pixelSize: 10
                                color: Theme.tokens.color.textSecondary
                            }
                        }
                    }
                }
            }
        }
    }
}
