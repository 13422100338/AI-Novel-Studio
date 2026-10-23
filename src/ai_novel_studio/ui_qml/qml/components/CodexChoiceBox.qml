import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ComboBox {
    id: root
    property string menuTitle: "选择模型"
    property bool compact: false
    property bool popupAbove: false
    property string secondaryText: ""
    property Component extraFooter: null
    implicitHeight: compact ? 30 : 36
    implicitWidth: compact ? Math.max(100, triggerMetrics.width + leftPadding + rightPadding + 4) : 180
    leftPadding: 12
    rightPadding: compact ? 8 : 30
    activeFocusOnTab: true
    font.pixelSize: compact ? 12 : 13
    Accessible.name: menuTitle
    ToolTip.visible: hovered && !popup.visible
    ToolTip.text: displayText
    ToolTip.delay: 600
    TextMetrics {
        id: triggerMetrics
        font: root.font
        text: root.displayText + (root.secondaryText ? " " + root.secondaryText : "")
    }
    contentItem: RowLayout {
        spacing: 4
        Text {
            Layout.fillWidth: true
            text: root.displayText
            textFormat: Text.PlainText
            font: root.font
            color: root.enabled ? Theme.tokens.color.textPrimary : Theme.tokens.color.textSecondary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        Text {
            objectName: root.compact ? "composerCodexEffortLabel" : ""
            Layout.maximumWidth: Math.min(90, root.availableWidth * 0.4)
            visible: root.secondaryText !== ""
            text: root.secondaryText
            textFormat: Text.PlainText
            font: root.font
            color: Theme.tokens.color.textSecondary
            elide: Text.ElideRight
        }
    }
    indicator: Text {
        visible: !root.compact
        x: root.width - width - 12
        y: (root.height - height) / 2
        text: "⌄"
        font.pixelSize: 15
        color: Theme.tokens.color.textSecondary
    }
    background: Rectangle {
        radius: root.compact ? height / 2 : 8
        color: root.compact ? (root.hovered || root.popup.visible ? Theme.tokens.color.hover : "transparent")
                            : Theme.tokens.color.bgEditor
        border.width: root.visualFocus || !root.compact ? 1 : 0
        border.color: root.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
    }
    delegate: ItemDelegate {
        required property int index
        objectName: root.objectName + "-choice-" + index
        width: choices.width
        implicitHeight: 40
        highlighted: root.highlightedIndex === index
        leftPadding: 12
        rightPadding: 12
        contentItem: RowLayout {
            Text {
                Layout.fillWidth: true
                text: root.textAt(index)
                textFormat: Text.PlainText
                font.pixelSize: 14
                color: Theme.tokens.color.textPrimary
                elide: Text.ElideRight
            }
            Text {
                objectName: root.objectName + "-selected-" + index
                visible: root.currentIndex === index
                text: "✓"
                font.pixelSize: 17
                color: Theme.tokens.color.textPrimary
            }
        }
        background: Rectangle {
            radius: 8
            color: parent.highlighted || parent.hovered ? Theme.tokens.color.hover : "transparent"
        }
    }
    popup: Popup {
        objectName: root.objectName + "Popup"
        y: root.popupAbove ? -height - 8 : root.height + 6
        x: Math.min(0, (root.Window.window ? root.Window.window.width : 400)
            - root.mapToItem(null, 0, 0).x - width - 12)
        width: Math.min(340, Math.max(260, root.width))
        implicitHeight: Math.min(460, Math.max(80, choices.contentHeight + 20 + bottomPadding - 10))
        padding: 10
        bottomPadding: footerLoader.item ? footerLoader.height + 20 : 10
        margins: 8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        contentItem: ListView {
            id: choices
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            header: Text {
                width: choices.width
                height: 32
                leftPadding: 12
                topPadding: 4
                text: root.menuTitle
                font.pixelSize: 12
                color: Theme.tokens.color.textSecondary
            }
            footer: Text {
                visible: root.count === 0
                width: choices.width
                height: visible ? 28 : 0
                text: "暂无选项，请刷新 Codex 连接。"
                font.pixelSize: 12
                color: Theme.tokens.color.textSecondary
            }
            ScrollBar.vertical: AppScrollBar { visible: size < 1 }
        }
        background: Rectangle {
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
            radius: 18
        }
        Loader {
            id: footerLoader
            parent: root.popup.background
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 10
            height: item ? item.implicitHeight : 0
            sourceComponent: root.extraFooter
        }
    }
}
