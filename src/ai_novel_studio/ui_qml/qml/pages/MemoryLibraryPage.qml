import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "memoryLibraryPage"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "旧资料 · 只读"
                font.pixelSize: 17
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "openLegacyAdvancedButton"
                text: "更多旧资料"
                ghost: true
                onClicked: Facade.setActiveNav("advanced")
            }
        }
        Text {
            Layout.fillWidth: true
            text: "这里保留旧版人物与记忆记录。当前创作以完整大纲和正式正文为依据，不再自动整理这些资料。"
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
        }

        TabBar {
            id: tabs
            objectName: "memoryLibraryTabs"
            Layout.fillWidth: true
            background: Rectangle {
                color: "transparent"
            }
            Repeater {
                model: ["人物", "记忆记录"]
                delegate: ThemedTabButton {
                    text: modelData
                    checked: tabs.currentIndex === index
                    onClicked: tabs.currentIndex = index
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            CharactersPage {}
            MemoryPage {}
        }
    }
}
