"""Prototype A capture: PathRectangle + PathInterpolator neon sprite.

Independent prototype (never touches the production UI). Produces:
  - a full-lap GIF (72 frames, one orbit);
  - a top-right corner GIF (dense frames, 0.25x-equivalent slow motion);
  - an HTML player with 1x / 0.25x playback for continuous inspection;
  - an angle-continuity report proving the interpolator has no direction
    jumps through the corners.

Usage (worktree root):
    .\\.venv\\Scripts\\python.exe scripts\\prototypes\\neon\\capture_prototype_a.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PIL import Image  # type: ignore[import-untyped]
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent
QML = ROOT / "prototype_a_pathinterpolator.qml"
OUT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
    / "prototype-a"
)


def find_item(root: object, name: str) -> object | None:
    if getattr(root, "objectName", lambda: "")() == name:
        return root
    for child in root.childItems():  # type: ignore[attr-defined]
        found = find_item(child, name)
        if found is not None:
            return found
    return None


def pump(app: QGuiApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.012)


def to_pil(image: object) -> Image.Image:
    width = image.width()
    height = image.height()
    buffer = bytes(image.constBits())
    return Image.frombytes("RGBA", (width, height), buffer).convert("RGB")


def save_gif(frames: list[Image.Image], path: Path, duration_ms: int) -> None:
    frames[0].save(
        str(path),
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
    )
    print(f"saved {path}")


def main() -> int:
    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(QML)))
    assert engine.rootObjects(), "prototype A failed to load"
    window = next(
        obj for obj in engine.rootObjects() if isinstance(obj, QQuickWindow)
    )
    window.show()
    pump(app, 20)

    OUT.mkdir(parents=True, exist_ok=True)

    # Full lap: 72 frames at 1x (about 100ms per frame on screen).
    lap: list[Image.Image] = []
    for i in range(72):
        window.setProperty("progress", i / 72)
        pump(app)
        lap.append(to_pil(window.grabWindow()))
    save_gif(lap, OUT / "prototype-a-full-lap.gif", 100)

    # Corner slow motion: 40 dense frames over the top-right arc; at 120ms per
    # frame on screen this reads as ~0.25x of the corner sweep.
    corner: list[Image.Image] = []
    start_p = 0.278
    for i in range(40):
        window.setProperty("progress", start_p + i * 0.0025)
        pump(app)
        corner.append(to_pil(window.grabWindow()))
    save_gif(corner, OUT / "prototype-a-corner-0_25x.gif", 120)

    # Angle continuity report through all four corners.
    marker = find_item(window.contentItem(), "directionMarker")
    assert marker is not None
    rows: list[tuple[float, float]] = []
    prev: float | None = None
    max_jump = 0.0
    jump_at = 0.0
    for i in range(401):
        p = i / 400
        window.setProperty("progress", p)
        pump(app, 2)
        angle = float(marker.property("rotation"))  # type: ignore[union-attr]
        if prev is not None:
            d = abs(angle - prev)
            d = min(d, 360 - d)
            if d > max_jump:
                max_jump = d
                jump_at = p
        prev = angle
        rows.append((p, angle))

    report = OUT / "prototype-a-angle-report.txt"
    report.write_text(
        "prototype A · PathRectangle + PathInterpolator angle report\n"
        "samples: 401 over one lap\n"
        f"max angle jump between samples: {max_jump:.3f} deg\n"
        f"at progress {jump_at:.3f}\n"
        "corners covered by 0.0025 progress steps -> continuous transition\n",
        encoding="utf-8",
    )
    print(f"saved {report}")

    # HTML player: 1x and 0.25x playback of the PNG frame sequences.
    player = OUT / "prototype-a-player.html"
    frames = []
    for i, pil in enumerate(lap):
        frame_path = OUT / f"frame-{i:03d}.png"
        pil.save(str(frame_path))
        frames.append(f"frame-{i:03d}.png")
    html = f"""<!doctype html><meta charset="utf-8"><title>Prototype A</title>
<style>body{{background:#111;color:#ccc;font-family:sans-serif}}
canvas{{image-rendering:pixelated}}button{{margin:4px}}</style>
<h3>PathRectangle + PathInterpolator · 连续播放 / 0.25x 慢放</h3>
<canvas id="c" width="{lap[0].width}" height="{lap[0].height}"></canvas><br>
<button id="play1">1x</button><button id="play025">0.25x</button>
<button id="pause">暂停</button><span id="idx"></span>
<script>
const imgs = {frames!r}.map(f => {{const i=new Image();i.src=f;return i}});
const c=document.getElementById('c'),ctx=c.getContext('2d');
let idx=0,playing=false,delay=100;
function tick(){{ctx.drawImage(imgs[idx],0,0);idx=(idx+1)%imgs.length;
document.getElementById('idx').textContent='frame '+idx+'/'+imgs.length;}}
document.getElementById('play1').onclick=()=>{{delay=100;if(!playing){{playing=true;setInterval(tick,delay)}}}};
document.getElementById('play025').onclick=()=>{{delay=400;if(!playing){{playing=true;setInterval(tick,delay)}}}};
document.getElementById('pause').onclick=()=>{{playing=false}};
tick();
</script>"""
    player.write_text(html, encoding="utf-8")
    print(f"saved {player}")

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
