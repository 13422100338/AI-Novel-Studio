"""Locate the neon border band in the resize screenshots and report its
geometry, proving the shader hugs the card at each window size."""

from __future__ import annotations

from pathlib import Path

from PIL import Image  # type: ignore[import-untyped]

OUT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
    / "prototype-b"
)


def border_geometry(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    print(f"{path.name}: {w}x{h}")
    # Neon blue family with tolerance for the core/halo mix.
    xs, ys = [], []
    count = 0
    for y in range(h):
        for x in range(w):
            r, g, b = img.getpixel((x, y))
            if b > 140 and r > 60 and r < 240 and g > 80 and g < 250 and b > r:
                xs.append(x)
                ys.append(y)
                count += 1
    print("  blue pixels:", len(xs))
    if xs:
        print("  border bbox x:", min(xs), "-", max(xs),
              " y:", min(ys), "-", max(ys))
        # The card border is the largest connected cluster; use a cheap
        # row/column histogram to find the card band.
        row_counts = {}
        col_counts = {}
        for x, y in zip(xs, ys, strict=True):
            row_counts[y] = row_counts.get(y, 0) + 1
            col_counts[x] = col_counts.get(x, 0) + 1
        card_rows = [y for y, c in row_counts.items() if c > 100]
        card_cols = [x for x, c in col_counts.items() if c > 100]
        if card_rows and card_cols:
            print(
                "  card border y range:", min(card_rows), "-", max(card_rows),
                " x range:", min(card_cols), "-", max(card_cols),
            )
    # Colour histogram for diagnostics.
    import collections
    hist = collections.Counter(img.getdata())
    print("  top colors:", hist.most_common(5))


def main() -> int:
    for name in ("prototype-b-resize-760x520.png", "prototype-b-resize-1080x620.png"):
        p = OUT / name
        if p.exists():
            border_geometry(p)
        else:
            print("missing:", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
