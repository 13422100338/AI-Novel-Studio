import QtQuick

// Production neon energy border (prototype B, user-accepted): a pure shader
// effect. No QML light item moves; the fragment shader computes per pixel:
//  1. rounded-rect SDF;
//  2. border mask;
//  3. continuous perimeter coordinate of the border;
//  4. ring distance between the current phase and the pixel's perimeter pos;
//  5. bright core;
//  6. smooth tail;
//  7. low-alpha outer halo.
// phase is driven by a UniformAnimator on the render thread, so corners are
// handled by the same continuous perimeter function - no item rotation, no
// per-segment QML objects, no canvas light sprite.
//
// State machine (same contract as the old Canvas StreamingGlowBorder):
//  - thinking/generating loop forever;
//  - success/error sweep once and stop;
//  - cancelled fades out once;
//  - idle = static border;
//  - reduceMotion / Safe tier / shader failure / hidden window degrade to
//    the static highlight border.
Item {
    id: root

    property bool active: false
    property string state: "" // "" | thinking | generating | success | error | cancelled | idle
    property real radius: 12
    property real glowWidth: 1.5
    property real coreRadius: 3.0
    property real tailLength: 30
    property real haloRadius: 10
    property int flowDuration: 2200
    property int fadeDuration: 700

    // Guarded Facade / Theme access (context properties can be null early).
    readonly property bool reduce:
        typeof Facade !== "undefined" && Facade ? Facade.reduceMotion : false
    readonly property bool safeTier:
        typeof Theme !== "undefined" && Theme
            ? Theme.visualQuality === "safe"
            : false
    readonly property bool windowVisible:
        typeof root.window === "undefined" || root.window === null
            ? true
            : root.window.visible

    // State colors follow the Agent tokens (same mapping as the old border).
    readonly property color stateColor: {
        if (!root.active) {
            return "transparent"
        }
        if (root.state === "success") {
            return Theme.tokens.agent.success
        }
        if (root.state === "error") {
            return Theme.tokens.agent.error
        }
        if (root.state === "cancelled") {
            return Theme.tokens.agent.cancelled
        }
        if (root.state === "generating") {
            return Theme.tokens.agent.generatingA
        }
        return Theme.tokens.agent.thinkingA
    }

    readonly property bool looping:
        root.active
        && (root.state === "" || root.state === "thinking"
            || root.state === "generating")
    readonly property bool singleShot:
        root.active
        && (root.state === "success" || root.state === "error")
    readonly property bool fadingOut:
        root.active && root.state === "cancelled"
    readonly property bool idleStatic:
        !root.active || root.state === "idle" || root.reduce
        || root.safeTier || !root.windowVisible

    // The flowing layer runs only while every condition holds.
    readonly property bool neonActive:
        root.active
        && root.visible
        && !root.reduce
        && !root.safeTier
        && root.windowVisible
        && !root.singleFinished
        && !root.cancelFaded

    // Shader health: QQuickShaderEffect::Status is unreliable through QML
    // bindings in this environment (stays 0 even when the shader compiles and
    // renders). The shader log is only set on failure, so an empty log while
    // active is our compiled marker (proven by the prototype B coverage test).
    readonly property int shaderStatus: effect.status
    readonly property bool shaderReady:
        effect.log.length === 0 && root.active
    readonly property string shaderLog: effect.log

    // Animation/test hooks (compat with the old Canvas implementation).
    readonly property bool animationRunning: loopAnim.running || singleAnim.running
    readonly property bool loopAnimRunning: loopAnim.running
    readonly property bool fadeAnimRunning: fadeAnim.running
    readonly property color frameColor: frame.border.color
    property bool singleFinished: false
    property bool cancelFaded: false
    property real phase: 0.0
    property int paintCount: 0

    onStateChanged: {
        root.singleFinished = false
        root.cancelFaded = false
    }

    // Static fallback border (Safe / reduceMotion / idle / shader failure /
    // single-shot finished / cancelled faded).
    Rectangle {
        id: frame
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.width: root.active ? root.glowWidth : 0
        border.color: root.stateColor
    }

    // The effect layer expands beyond the card by the halo radius so the
    // glow can spill outside the edge. It never participates in layout and
    // ShaderEffect does not receive mouse events, so neighbors stay
    // interactive.
    readonly property real haloOutset: Math.max(root.haloRadius, 8)

    ShaderEffect {
        id: effect
        objectName: "neonShaderEffect"
        anchors.fill: parent
        anchors.margins: -root.haloOutset
        visible: root.neonActive
        opacity: root.cancelFaded ? 0 : 1

        property vector2d uSize: Qt.vector2d(root.width, root.height)
        property real uRadius: root.radius
        property real uBorderWidth: root.glowWidth
        property real uPhase: 0.0
        property color uColor: root.stateColor
        property real uCoreRadius: root.coreRadius
        property real uTailLength: root.tailLength
        property real uHaloRadius: root.haloRadius
        property real uDpr: typeof root.window !== "undefined"
            && root.window !== null ? root.window.devicePixelRatio : 1.0
        property real uOutset: root.haloOutset

        fragmentShader: Qt.resolvedUrl("neon_rounded_border.qsb")

        onStatusChanged: {
            if (effect.status === 2) {
                console.warn("[neon] shader failed:", effect.log)
            }
        }
    }

    UniformAnimator {
        id: loopAnim
        target: effect
        uniform: "uPhase"
        from: 0
        to: 1
        duration: root.flowDuration
        loops: Animation.Infinite
        running: root.looping && root.neonActive && root.shaderReady
    }

    UniformAnimator {
        id: singleAnim
        target: effect
        uniform: "uPhase"
        from: 0
        to: 1
        duration: root.flowDuration
        loops: 1
        running: root.singleShot && root.neonActive
            && root.shaderReady && !root.singleFinished
        onFinished: root.singleFinished = true
    }

    // Cancelled: fade the flowing layer out once, then stay gone.
    NumberAnimation {
        id: fadeAnim
        target: effect
        property: "opacity"
        from: 1.0
        to: 0.0
        duration: root.fadeDuration
        loops: 1
        running: root.fadingOut && root.neonActive
            && !root.cancelFaded && root.shaderReady
        easing.type: Easing.OutCubic
        onFinished: root.cancelFaded = true
    }
}
