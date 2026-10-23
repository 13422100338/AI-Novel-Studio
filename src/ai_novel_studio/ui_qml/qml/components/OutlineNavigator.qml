import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    objectName: "outlineNavigator"
    property string query: ""
    readonly property var outline: Facade.outline
    readonly property var view: outline.state
    readonly property var navigation: outline.navigation
    spacing: 12
    Text {
        text: "大纲导航"
        font.pixelSize: 12
        font.bold: true
        color: Theme.tokens.color.textSecondary
    }
    ComboBox {
        id: documents
        objectName: "outlineDocuments"
        Layout.fillWidth: true
        visible: root.view.documents.length > 0
        model: root.view.documents
        textRole: "title"
        valueRole: "id"
        currentIndex: root.view.currentIndex
        onActivated: root.outline.selectDocument(currentValue)
        palette.text: Theme.tokens.color.textPrimary
        background: Rectangle { color: Theme.tokens.color.bgCanvas; border.color: Theme.tokens.color.border; radius: 8 }
        contentItem: Text {
            text: documents.displayText
            leftPadding: 10; rightPadding: 25
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 13
            color: Theme.tokens.color.textPrimary
        }
        popup.background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 8 }
    }
    ListView {
        id: list
        objectName: "outlineHeadingList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 3
        rightMargin: 10
        model: root.view.headings.filter(function(item) { return item.title.toLowerCase().indexOf(root.query.toLowerCase()) >= 0 })
        ScrollBar.vertical: AppScrollBar { visible: size < 1 }
        delegate: ItemDelegate {
            required property var modelData
            objectName: "outline-nav-heading-" + modelData.line
            width: list.width - list.rightMargin
            implicitHeight: Math.max(40, caption.implicitHeight + 16)
            leftPadding: 10 + Math.min(4, modelData.level - 1) * 10
            rightPadding: 8
            text: OutlineMarkup.title(modelData.title)
            onClicked: root.outline.selectHeading(modelData.line)
            contentItem: Text {
                id: caption
                text: parent.text
                font.pixelSize: modelData.level <= 2 ? 13 : 12
                font.bold: modelData.level <= 2
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: root.navigation.headingLine === modelData.line ? Theme.tokens.color.accent : Theme.tokens.color.textPrimary
            }
            background: Rectangle {
                radius: 8
                color: root.navigation.headingLine === modelData.line ? Theme.tokens.color.pressed
                    : parent.hovered ? Theme.tokens.color.hover : "transparent"
            }
        }
        Text {
            anchors.centerIn: parent
            visible: list.count === 0
            width: parent.width - 16
            text: root.view.loaded ? "暂无匹配的标题或编号事件" : "导入或新建大纲后，目录显示在这里"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            color: Theme.tokens.color.textSecondary
        }
    }
}
