import QtQuick

// Vector navigation icons (clean modern flat design): one consistent
// stroke style for every rail entry, replacing the mixed-weight Unicode
// glyphs (✎ ▤ ✦ ⚙). Canvas drawing keeps the icons crisp at any DPI and
// perfectly centered (no font-metric surprises).
Canvas {
    id: root

    // One of: "writing" | "library" | "advanced" | "settings".
    property string kind: ""
    property color iconColor: Theme.tokens.color.textSecondary

    width: 20
    height: 20

    onKindChanged: requestPaint()
    onIconColorChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.strokeStyle = root.iconColor
        ctx.lineWidth = 1.7
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.beginPath()

        if (root.kind === "writing") {
            // Pencil (Feather "edit-2" geometry scaled to a 20px grid).
            ctx.moveTo(14.2, 2.5)
            ctx.lineTo(17.5, 5.8)
            ctx.lineTo(6.7, 16.7)
            ctx.lineTo(2.5, 17.5)
            ctx.lineTo(3.3, 13.3)
            ctx.closePath()
        } else if (root.kind === "library") {
            // Closed book: cover outline + spine.
            ctx.rect(4, 3, 12, 14)
            ctx.moveTo(7, 3)
            ctx.lineTo(7, 17)
        } else if (root.kind === "advanced") {
            // Four-point sparkle (concave edges curve toward the center).
            ctx.moveTo(10, 2.5)
            ctx.quadraticCurveTo(10.9, 9.1, 17.5, 10)
            ctx.quadraticCurveTo(10.9, 10.9, 10, 17.5)
            ctx.quadraticCurveTo(9.1, 10.9, 2.5, 10)
            ctx.quadraticCurveTo(9.1, 9.1, 10, 2.5)
            ctx.closePath()
        } else if (root.kind === "settings") {
            // Gear: ring + 8 teeth + hub.
            ctx.arc(10, 10, 5.5, 0, 2 * Math.PI)
            for (var i = 0; i < 8; i += 1) {
                var a = i * Math.PI / 4
                ctx.moveTo(10 + Math.cos(a) * 6.8, 10 + Math.sin(a) * 6.8)
                ctx.lineTo(10 + Math.cos(a) * 8.6, 10 + Math.sin(a) * 8.6)
            }
            ctx.moveTo(12.2, 10)
            ctx.arc(10, 10, 2.2, 0, 2 * Math.PI)
        }

        ctx.stroke()
    }
}
