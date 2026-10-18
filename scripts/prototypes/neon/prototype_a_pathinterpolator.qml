import QtQuick

// Prototype A (user direction, glassmorphism-ui-log.md §25): validate whether
// Qt 6.8+ PathRectangle + PathInterpolator remove the corner position/angle
// discontinuities of the hand-rolled four-edge/four-arc path.
//
// The glow sprite is a small circular light (no capsule, no carriage) driven
// ONLY by PathInterpolator over the native PathRectangle path. The harness
// grabs a full lap plus a dense corner pass and checks the interpolated angle
// for jumps.
Window {
    id: root
    objectName: "prototypeAWindow"
    width: 560
    height: 360
    visible: true
    color: "#202124"
    title: "Prototype A · PathRectangle + PathInterpolator"

    // Progress hook for the harness (0..1).
    property real progress: 0.0
    property int cornerFrames: 0

    // Native rounded-rect path: Qt 6.8+ PathRectangle segment.
    Path {
        id: track
        startX: 120
        startY: 116
        PathRectangle {
            x: 120
            y: 100
            width: 320
            height: 160
            topLeftRadius: 16
            topRightRadius: 16
            bottomLeftRadius: 16
            bottomRightRadius: 16
        }
    }
    // Visual reference border (PathRectangle itself only exposes the Path).
    Rectangle {
        objectName: "trackBorder"
        x: 120
        y: 100
        width: 320
        height: 160
        radius: 16
        color: "transparent"
        border.color: "#4A4E55"
        border.width: 1
    }

    PathInterpolator {
        id: interpolator
        path: track
        progress: root.progress
    }

    // The moving light: concentric circles, no rotation needed for a dot, but
    // the angle is exposed for the harness continuity check.
    Item {
        id: sprite
        objectName: "glowSprite"
        x: interpolator.x - sprite.width / 2
        y: interpolator.y - sprite.height / 2
        width: 20
        height: 20

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "#8AB4F8"
            opacity: 0.22
        }
        Rectangle {
            anchors.centerIn: parent
            width: 10
            height: 10
            radius: width / 2
            color: "#D7E6FF"
        }
        Rectangle {
            anchors.centerIn: parent
            width: 4
            height: 4
            radius: width / 2
            color: "white"
        }
    }

    // Small direction marker (rotates with the interpolated angle so corner
    // angle continuity is visible both in pixels and in the harness log).
    Item {
        id: directionMarker
        objectName: "directionMarker"
        x: interpolator.x
        y: interpolator.y
        width: 24
        height: 24
        rotation: interpolator.angle

        Rectangle {
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            width: 2
            height: 12
            color: "#FFD166"
        }
    }

    Text {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.margins: 12
        text: "progress " + root.progress.toFixed(3)
            + " · angle " + interpolator.angle.toFixed(1) + "°"
        font.pixelSize: 12
        color: "#AEB2B7"
    }
}
