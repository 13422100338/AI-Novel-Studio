import QtQuick
import QtQuick.Layouts
import "../surfaces"

Item {
    id: root

    implicitWidth: 56

    // Production-shell integration: when the caller passes the window's
    // backdrop layer, the rail renders as a flat opaque panel (clean modern
    // shell: no capture, no blur). Without it the rail keeps its original
    // opaque background, so standalone uses are unaffected.
    property Item backdropSource: null

    AcrylicSurface {
        anchors.fill: parent
        visible: root.backdropSource !== null
        sourceItem: root.backdropSource
        opaqueFallback: true
        radius: 16
        objectName: "navRailGlass"
    }
    Rectangle {
        anchors.fill: parent
        visible: root.backdropSource === null
        color: Theme.tokens.color.bgSurface
        border.color: Theme.tokens.color.border
        border.width: 1
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        spacing: 10

        Item {
            Layout.preferredHeight: 4
        }

        // Full-width rows: the selected tint and accent bar span the whole
        // rail (bar flush with the rail's left edge) while the icon + label
        // stay centered -- same selection language as the chapter list.
        Repeater {
            model: [
                { id: "writing", kind: "writing", label: "写作" },
                { id: "library", kind: "library", label: "记忆库" },
                { id: "advanced", kind: "advanced", label: "高级创作" },
                { id: "settings", kind: "settings", label: "设置" }
            ]
            delegate: IconButton {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                radius: 12
                objectName: "nav-" + modelData.id
                iconKind: modelData.kind
                text: modelData.label
                selected: Facade.activeNav === modelData.id
                onClicked: Facade.setActiveNav(modelData.id)
            }
        }

        Item {
            Layout.fillHeight: true
        }
    }
}
