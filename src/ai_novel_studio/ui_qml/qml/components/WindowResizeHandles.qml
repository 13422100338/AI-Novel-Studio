import QtQuick
import QtQuick.Window

Item {
    id: root
    property var targetWindow
    anchors.fill: parent
    enabled: targetWindow && targetWindow.visibility !== Window.Maximized && targetWindow.visibility !== Window.FullScreen
    z: 100
    Repeater {
        model: [
            {edge: Qt.LeftEdge, side: "left", cursor: Qt.SizeHorCursor},
            {edge: Qt.RightEdge, side: "right", cursor: Qt.SizeHorCursor},
            {edge: Qt.TopEdge, side: "top", cursor: Qt.SizeVerCursor},
            {edge: Qt.BottomEdge, side: "bottom", cursor: Qt.SizeVerCursor},
            {edge: Qt.LeftEdge | Qt.TopEdge, side: "tl", cursor: Qt.SizeFDiagCursor},
            {edge: Qt.RightEdge | Qt.TopEdge, side: "tr", cursor: Qt.SizeBDiagCursor},
            {edge: Qt.LeftEdge | Qt.BottomEdge, side: "bl", cursor: Qt.SizeBDiagCursor},
            {edge: Qt.RightEdge | Qt.BottomEdge, side: "br", cursor: Qt.SizeFDiagCursor}
        ]
        delegate: MouseArea {
            required property var modelData
            readonly property bool corner: modelData.side.length === 2
            width: corner ? 12 : modelData.side === "left" || modelData.side === "right" ? 5 : root.width - 24
            height: corner ? 12 : modelData.side === "top" || modelData.side === "bottom" ? 5 : root.height - 24
            x: modelData.side === "right" || modelData.side.endsWith("r") ? root.width - width : corner || modelData.side === "left" ? 0 : 12
            y: modelData.side === "bottom" || modelData.side.startsWith("b") ? root.height - height : corner || modelData.side === "top" ? 0 : 12
            cursorShape: modelData.cursor
            acceptedButtons: Qt.LeftButton
            onPressed: root.targetWindow.startSystemResize(modelData.edge)
        }
    }
}
