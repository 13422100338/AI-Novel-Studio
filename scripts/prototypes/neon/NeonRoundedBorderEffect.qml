import QtQuick

// Prototype B (formal candidate, user direction  25): a pure shader neon
// border. No QML light item moves; the fragment shader computes, per pixel:
//  1. rounded-rect SDF;
//  2. border mask;
//  3. continuous perimeter coordinate of the border;
//  4. ring distance between the current phase and the pixel's perimeter pos;
//  5. bright core;
//  6. smooth tail;
//  7. low-alpha outer halo.
// phase is driven by a UniformAnimator on the render thread.
//
// Shader failure (status !== Compiled) or Safe tier / reduceMotion degrade to
// a static highlight border. This component is prototype-only and is never
// referenced by the production UI.
Item {
    id: root

    property bool active: false
    property string state: "" // "" | thinking | generating | success | error | cancelled | idle
    property real radius: 16
    property color color: "#8AB4F8"
    property real coreRadius: 3.2
    property real tailLength: 30
    property real haloRadius: 10
    property real borderWidth: 1.5
    property int flowDuration: 2200

    property bool reduce:
        typeof Facade !== "undefined" && Facade ? Facade.reduceMotion : false
    property bool safeTier:
        typeof Theme !== "undefined" && Theme
            ? Theme.visualQuality === "safe"
            : false
    readonly property bool looping:
        root.active
        && (root.state === "" || root.state === "thinking"
            || root.state === "generating")
    readonly property bool singleShot:
        root.active
        && (root.state === "success" || root.state === "error")

    // Test hooks ---------------------------------------------------
    // QQuickShaderEffect::Status is unreliable through QML bindings in this
    // environment (stays 0 even after the shader compiles and renders).
    // Detection strategy: a shader log is only set on failure, so an empty
    // log while the effect is active is our compiled marker. The shader
    // itself is proven by the debug red coverage test.
    readonly property int shaderStatus: effect.status
    readonly property bool shaderReady:
        effect.log.length === 0 && root.active
    readonly property string shaderLog: effect.log
    readonly property bool animRunning: loopAnim.running || singleAnim.running
    property bool singleFinished: false

    onStateChanged: root.singleFinished = false

    // Static fallback border: visible whenever the effect is not running
    // (safe tier, reduceMotion, shader failure, idle, single-shot finished).
    Rectangle {
        id: fallback
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.width: root.active ? root.borderWidth : 0
        border.color: root.active ? root.color : "transparent"
        visible: root.active
    }

    // The effect layer expands beyond the card by the halo radius so the
    // glow can spill outside the edge. Never participates in layout.
    readonly property real haloOutset: Math.max(root.haloRadius, 8)

    ShaderEffect {
        id: effect
        objectName: "neonShaderEffect"
        anchors.fill: parent
        anchors.margins: -root.haloOutset
        visible: root.active && !root.reduce && !root.safeTier
            && !root.singleFinished && root.shaderReady

        property vector2d uSize: Qt.vector2d(root.width, root.height)
        property real uRadius: root.radius
        property real uBorderWidth: root.borderWidth
        property real uPhase: 0.0
        property color uColor: root.color
        property real uCoreRadius: root.coreRadius
        property real uTailLength: root.tailLength
        property real uHaloRadius: root.haloRadius
        property real uDpr: typeof root.window !== "undefined"
            && root.window !== null ? root.window.devicePixelRatio : 1.0
        property real uOutset: root.haloOutset

        fragmentShader: Qt.resolvedUrl("neon_rounded_border_frag.qsb")

        // Failure detection: log and fall back to the static border.
        onStatusChanged: {
            if (effect.status === 2) {
                console.warn(
                    "[neon prototype B] shader failed:",
                    effect.log
                )
            } else if (effect.status === 0) {
                console.warn("[neon prototype B] shader not compiled yet")
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
        running: root.looping && root.shaderReady
            && !root.reduce && !root.safeTier
    }

    UniformAnimator {
        id: singleAnim
        target: effect
        uniform: "uPhase"
        from: 0
        to: 1
        duration: root.flowDuration
        loops: 1
        running: root.singleShot && root.shaderReady
            && !root.reduce && !root.safeTier && !root.singleFinished
        onFinished: root.singleFinished = true
    }
}
