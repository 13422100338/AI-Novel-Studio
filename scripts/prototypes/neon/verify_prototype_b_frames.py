"""Verify prototype B frames: distinctness, motion, and light position."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageChops  # type: ignore[import-untyped]

OUT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
    / "prototype-b"
)


def main() -> int:
    frames = sorted(OUT.glob("frame-*.png"))
    print("frames:", len(frames))
    diffs = 0
    seen: set[str] = set()
    prev: Image.Image | None = None
    for f in frames:
        img = Image.open(f).convert("RGB")
        if prev is not None and ImageChops.difference(prev, img).getbbox() is not None:
            diffs += 1
        seen.add(hashlib.md5(f.read_bytes()).hexdigest())
        prev = img
    print("consecutive changed:", diffs, "/", len(frames) - 1)
    print("distinct frames:", len(seen))

    for idx in (0, 12, 24, 36, 48, 60, 71):
        img = Image.open(OUT / f"frame-{idx:03d}.png").convert("RGB")
        best = max(
            ((r + g + b, x, y)
             for y in range(img.height)
             for x in range(img.width)
             for r, g, b in [img.getpixel((x, y))]),
            default=None,
        )
        print(f"frame {idx}: brightest {best}")

    for label in ("resize-240x200", "resize-480x220", "reducemotion-static", "safe-static"):
        f = OUT / f"prototype-b-{label}.png"
        if not f.exists():
            continue
        img = Image.open(f).convert("RGB")
        # Neon-blue border pixels only (the shader's uColor #8AB4F8 family).
        xs = []
        ys = []
        count = 0
        for y in range(img.height):
            for x in range(img.width):
                p = img.getpixel((x, y))
                if p[2] > 150 and p[0] > 60 and p[0] < 220 and p[1] > 90 and p[1] < 240:
                    xs.append(x)
                    ys.append(y)
                    count += 1
        if xs:
            print(
                f"{label}: border bbox x {min(xs)}-{max(xs)} "
                f"y {min(ys)}-{max(ys)} (w {max(xs)-min(xs)}, h {max(ys)-min(ys)}, "
                f"blue px {count})"
            )
        else:
            print(f"{label}: no border pixels found")

    # Corner slow-motion GIF: verify the light actually rounds a corner
    # (moves along both edges and across the corner arc) with continuity.
    corner_path = OUT / "prototype-b-corner-0_25x.gif"
    if corner_path.exists():
        with Image.open(corner_path) as gif:
            n = getattr(gif, "n_frames", 1)
            positions = []
            for i in range(n):
                gif.seek(i)
                img = gif.convert("RGB")
                best = max(
                    ((r + g + b, x, y)
                     for y in range(img.height)
                     for x in range(img.width)
                     for r, g, b in [img.getpixel((x, y))]),
                    default=None,
                )
                positions.append(best)
            print("corner gif frames:", n)
            xs = [p[1] for p in positions if p]
            ys = [p[2] for p in positions if p]
            print("corner light x range:", min(xs), "-", max(xs))
            print("corner light y range:", min(ys), "-", max(ys))
            print("corner light positions:", positions[::6])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
