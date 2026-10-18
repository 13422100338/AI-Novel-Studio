import QtQuick

// StreamingGlowBorder - neon energy flow around the *currently active* Agent
// surface.
//
// Since prototype B was accepted by the user, the former Canvas light-sprite
// implementation is replaced by the production shader component
// NeonRoundedBorderEffect: one ShaderEffect paints core + tail + halo from a
// continuous perimeter function, driven by a render-thread UniformAnimator.
// This file stays as the compatibility layer that keeps the old public API
// (active/state/radius/glowWidth/coreRadius/tailLength/haloRadius/
// tailSamples/flowDuration/fadeDuration) and the test hooks
// (animationRunning/loopAnimRunning/fadeAnimRunning/frameColor/
// singleFinished/cancelFaded/phase/paintCount) so existing consumers and
// tests keep working unchanged.
Item {
    id: root

    property bool active: false
    // "" | "thinking" | "generating" | "success" | "error" | "cancelled" |
    // "idle"
    property string state: ""
    property real radius: 12
    property real glowWidth: 1.5

    // Neon parameters (shader reads these; tailSamples kept for API compat).
    property real coreRadius: 3.0
    property real tailLength: 30
    property real haloRadius: 10
    property int tailSamples: 24
    property int flowDuration: 2200
    property int fadeDuration: 700

    // Delegate everything to the production shader component.
    NeonRoundedBorderEffect {
        id: neon
        anchors.fill: parent
        active: root.active
        state: root.state
        radius: root.radius
        glowWidth: root.glowWidth
        coreRadius: root.coreRadius
        tailLength: root.tailLength
        haloRadius: root.haloRadius
        flowDuration: root.flowDuration
        fadeDuration: root.fadeDuration
    }

    // Test hooks ----------------------------------------------------
    readonly property bool animationRunning: neon.animationRunning
    readonly property bool loopAnimRunning: neon.loopAnimRunning
    readonly property bool fadeAnimRunning: neon.fadeAnimRunning
    readonly property color frameColor: neon.frameColor
    readonly property bool singleFinished: neon.singleFinished
    readonly property bool cancelFaded: neon.cancelFaded
    readonly property real phase: neon.phase
    readonly property int paintCount: neon.paintCount
}
