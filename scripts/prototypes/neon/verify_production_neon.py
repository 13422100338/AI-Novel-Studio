"""Verify the production neon screenshots contain glowing border pixels."""

from __future__ import annotations

from pathlib import Path

from PIL import Image  # type: ignore[import-untyped]

OUT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
)


def main() -> int:
    for name in ("c1-neon-thinking.png", "c1-neon-success.png"):
        path = OUT / name
        img = Image.open(path).convert("RGB")
        # Bright saturated pixels (neon core/halo are state-colored and much
        # brighter than the neutral card border). Count blue-purple for
        # thinking and green for success.
        blue = 0
        green = 0
        dark_green = 0
        for r, g, b in img.getdata():
            if b > 160 and r > 80 and r < 200 and g > 90 and g < 220:
                blue += 1
            if g > 150 and r < 140 and b < 160:
                green += 1
            # Static success border token #3E7C4F family.
            if 40 < r < 90 and 90 < g < 160 and 40 < b < 110 and g > r:
                dark_green += 1
        print(
            f"{name}: size={img.size} blue-neon={blue} bright-green={green} "
            f"dark-green={dark_green}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
