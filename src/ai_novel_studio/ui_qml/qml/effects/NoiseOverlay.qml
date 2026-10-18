import QtQuick

// Static, very low-contrast film grain (ideal-UI spec 4.2 "低透明噪声").
// Painted once into a canvas with a coarse grid so it costs nothing at idle;
// it is not animated and never runs on the GPU as a shader.
Canvas {
    id: root

    property real intensity: parseFloat(Theme.tokens.material.noiseOpacity)
    visible: Theme.visualQuality !== "safe" && intensity > 0
    opacity: intensity

    onPaint: {
        const ctx = root.getContext("2d")
        ctx.reset()
        const step = 4
        for (let y = 0; y < root.height; y += step) {
            for (let x = 0; x < root.width; x += step) {
                if (Math.random() < 0.18) {
                    ctx.fillStyle = Math.random() < 0.5 ? "#000000" : "#FFFFFF"
                    ctx.globalAlpha = 0.5
                    ctx.fillRect(x, y, 1, 1)
                }
            }
        }
    }

    onWidthChanged: root.requestPaint()
    onHeightChanged: root.requestPaint()
}
