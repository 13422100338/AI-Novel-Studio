import QtQuick

// Reusable iOS 26 "Liquid Glass" light layer (research-backed, see
// AcrylicSurface.qml header and docs/frontend/2026-08-04-glassmorphism-ui-log.md
// sections 12/14): top/left edge light + bottom/right inner shadow, painted
// once into a static Canvas and clipped to the rounded rect so no gradient
// ever leaks past the corners.
//
// Per user feedback the diagonal specular sheen is deliberately NOT part of
// this component: the light source is the BackdropLayer background glow that
// the glass blurs, not a highlight painted on the panel surface. Edge light +
// inner shadow stay as a faint, shared "light falls from the top-left"
// language across panels and cards.
//
// AgentCard and content cards use only edge light + inner shadow; Safe tier
// hides the whole layer by setting every strength to 0 (or the caller sets
// visible: false).
Canvas {
    id: root

    property real radius: 12
    property real edgeLightOpacity: 0
    property real innerShadowOpacity: 0

    onEdgeLightOpacityChanged: root.requestPaint()
    onInnerShadowOpacityChanged: root.requestPaint()
    onRadiusChanged: root.requestPaint()
    onWidthChanged: root.requestPaint()
    onHeightChanged: root.requestPaint()
    onVisibleChanged: root.requestPaint()

    function roundedRectPath(ctx, x, y, w, h, r) {
        const radius = Math.max(0, Math.min(r, w / 2, h / 2))
        ctx.beginPath()
        ctx.moveTo(x + radius, y)
        ctx.lineTo(x + w - radius, y)
        ctx.arcTo(x + w, y, x + w, y + radius, radius)
        ctx.lineTo(x + w, y + h - radius)
        ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius)
        ctx.lineTo(x + radius, y + h)
        ctx.arcTo(x, y + h, x, y + h - radius, radius)
        ctx.lineTo(x, y + radius)
        ctx.arcTo(x, y, x + radius, y, radius)
        ctx.closePath()
    }

    onPaint: {
        const ctx = root.getContext("2d")
        ctx.reset()
        const w = root.width
        const h = root.height
        const edge = root.edgeLightOpacity
        const inner = root.innerShadowOpacity
        if (edge <= 0 && inner <= 0) {
            return
        }
        const white = function (a) {
            return "rgba(255,255,255," + a.toFixed(3) + ")"
        }
        const black = function (a) {
            return "rgba(0,0,0," + a.toFixed(3) + ")"
        }

        ctx.save()
        root.roundedRectPath(ctx, 0, 0, w, h, root.radius)
        ctx.clip()

        // Top edge light: light gathering along the upper rim.
        if (edge > 0) {
            const top = ctx.createLinearGradient(0, 0, 0, 10)
            top.addColorStop(0.0, white(edge))
            top.addColorStop(1.0, white(0))
            ctx.fillStyle = top
            ctx.fillRect(0, 0, w, 10)

            // Left edge light: weaker rim on the lit side.
            const left = ctx.createLinearGradient(0, 0, 8, 0)
            left.addColorStop(0.0, white(edge * 0.55))
            left.addColorStop(1.0, white(0))
            ctx.fillStyle = left
            ctx.fillRect(0, 0, 8, h)
        }

        // Bottom/right inner shadow: material thickness; light falls from the
        // top-left.
        if (inner > 0) {
            const bottom = ctx.createLinearGradient(0, h, 0, h - 10)
            bottom.addColorStop(0.0, black(inner))
            bottom.addColorStop(1.0, black(0))
            ctx.fillStyle = bottom
            ctx.fillRect(0, h - 10, w, 10)

            const right = ctx.createLinearGradient(w, 0, w - 8, 0)
            right.addColorStop(0.0, black(inner * 0.8))
            right.addColorStop(1.0, black(0))
            ctx.fillStyle = right
            ctx.fillRect(w - 8, 0, 8, h)
        }

        ctx.restore()
    }
}
