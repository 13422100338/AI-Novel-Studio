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

        Text {
            text: "记忆库"
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        TabBar {
            id: tabs
            objectName: "memoryLibraryTabs"
            Layout.fillWidth: true
            background: Rectangle {
                color: "transparent"
            }
            Repeater {
                model: ["角色", "世界", "剧情记忆", "待处理"]
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
            EmptyState {
                title: "世界"
                body: "世界规则与设定将在后续 Wave 接入（当前复用记忆库结构）。"
            }
            MemoryPage {}
            EmptyState {
                title: "待处理"
                body: "待确认的整理候选将在这里展示。"
            }
        }
    }
}
