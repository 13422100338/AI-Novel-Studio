import QtQuick

// Static high-contrast highlight around the currently active Agent surface.
// Used directly when reduceMotion is on (the StreamingGlowBorder degrades to
// this color) and by the Visual V0 lab as the "Balanced" tier representation.
Rectangle {
    id: root

    property string tone: "thinking" // thinking | generating | success | error
    property real glowWidth: 1

    readonly property color toneColor: {
        switch (root.tone) {
        case "generating": return Theme.tokens.agent.generatingA
        case "success": return Theme.tokens.agent.success
        case "error": return Theme.tokens.agent.error
        default: return Theme.tokens.agent.thinkingA
        }
    }

    color: "transparent"
    border.width: root.glowWidth
    border.color: root.toneColor
    radius: root.radius
}
