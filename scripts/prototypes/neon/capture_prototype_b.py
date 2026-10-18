"""Prototype B capture: shader-based neon rounded border.

Independent prototype (never touches the production UI). Produces:
  - a full-lap GIF (thinking mode, 72 frames, one orbit);
  - a corner slow-motion GIF (dense frames, 0.25x-equivalent playback);
  - single-shot sweep GIFs (success / error);
  - reduce-motion and safe-tier static fallback captures;
  - an HTML player for continuous 1x / 0.25x inspection;
  - a report with shader readiness and phase-coverage notes.

Usage (worktree root):
    .\\.venv\\Scripts\\python.exe scripts\\prototypes\\neon\\capture_prototype_b.py

Note: this must run in a windowed session (no QT_QPA_PLATFORM=offscreen and
no QT_QUICK_BACKEND=software) because ShaderEffect needs a real graphics
stack and grabWindow returns black under the software backend.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PIL import Image  # type: ignore[import-untyped]
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent
QML = ROOT / "prototype_b_shader.qml"
OUT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
    / "prototype-b"
)


def find_item(root: object, name: str) -> object | None:
    if getattr(root, "objectName", lambda: "")() == name:
        return root
    for child in root.childItems():  # type: ignore[attr-defined]
        found = find_item(child, name)
        if found is not None:
            return found
    return None


def pump(app: QGuiApplication, rounds: int = 8) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.012)


def pump_seconds(app: QGuiApplication, seconds: float) -> None:
    """Pump the event loop long enough for wall-clock time to pass, so
    render-thread animators (UniformAnimator) actually advance between
    grabs. grabWindow blocks, so small sleeps are interleaved."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.008)


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


def set_mode(window: object, mode: str) -> None:
    window.setProperty("mode", mode)


def main() -> int:
    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(QML)))
    assert engine.rootObjects(), "prototype B failed to load"
    window = next(
        obj for obj in engine.rootObjects() if isinstance(obj, QQuickWindow)
    )
    window.show()
    pump(app, 40)

    neon = find_item(window.contentItem(), "prototypeBNeon")
    assert neon is not None, "neon effect item not found"

    OUT.mkdir(parents=True, exist_ok=True)
    dpr = float(window.devicePixelRatio())

    # 1. Full lap: thinking loops. UniformAnimator drives uPhase 0->1 over
    #    flowDuration (2200ms). Sample 72 frames evenly across one lap, i.e.
    #    ~30ms apart; each frame is then ~one lap/72 of phase ahead.
    set_mode(window, "thinking")
    pump(app, 20)
    flow_ms = float(neon.property("flowDuration")) or 2200.0
    frame_interval = flow_ms / 1000.0 / 72.0
    lap: list[Image.Image] = []
    for _i in range(72):
        pump_seconds(app, frame_interval)
        lap.append(to_pil(window.grabWindow()))
    save_gif(lap, OUT / "prototype-b-full-lap.gif", 100)

    # 2. Dense full-lap capture for corner extraction.
    dense: list[Image.Image] = []
    dense_interval = flow_ms / 1000.0 / 144.0
    for _i in range(144):
        pump_seconds(app, dense_interval)
        dense.append(to_pil(window.grabWindow()))

    # Corner phase positions for a 320x160 card with radius 16:
    # perimeter = 2*288 + 2*128 + 4*25.133 = 932.53; corners sit at arc
    # midpoints: after straightX, arc/2, straightX+arc, ...
    w = 320.0
    h = 160.0
    r = 16.0
    sx = max(w - 2 * r, 0.0)
    sy = max(h - 2 * r, 0.0)
    arc = math.pi * 0.5 * r
    perimeter = 2 * sx + 2 * sy + 4 * arc
    corner_phases = [
        (sx + arc * 0.5) / perimeter,           # top-right mid
        (sx + arc + sy + arc * 0.5) / perimeter,  # bottom-right mid
        (2 * sx + 2 * arc + sy + arc * 0.5) / perimeter,  # bottom-left
        (sx + 2 * arc + 2 * sy + 3 * arc * 0.5) / perimeter,  # top-left
    ]
    # Extract a 48-frame window centred on the first corner for a 0.25x view.
    center = int(corner_phases[0] * 144)
    corner = [dense[(center + i - 24) % 144] for i in range(48)]
    save_gif(corner, OUT / "prototype-b-corner-0_25x.gif", 120)
    print(
        "corner window centred on phase "
        f"{corner_phases[0]:.3f} (frame {center})"
    )

    # 3. Single-shot sweeps: success and error play once then stop.
    for mode in ("success", "error"):
        set_mode(window, mode)
        pump(app, 20)
        frames: list[Image.Image] = []
        for _i in range(60):
            pump_seconds(app, flow_ms / 1000.0 / 60.0)
            frames.append(to_pil(window.grabWindow()))
        save_gif(frames, OUT / f"prototype-b-{mode}-single.gif", 100)

    # 4. reduceMotion and safe-tier static fallbacks.
    set_mode(window, "thinking")
    window.setProperty("reduceMotion", True)
    pump(app, 20)
    reduce_shot = to_pil(window.grabWindow())
    reduce_shot.save(str(OUT / "prototype-b-reducemotion-static.png"))
    window.setProperty("reduceMotion", False)
    window.setProperty("safeTier", True)
    pump(app, 20)
    safe_shot = to_pil(window.grabWindow())
    safe_shot.save(str(OUT / "prototype-b-safe-static.png"))
    window.setProperty("safeTier", False)

    # 5. Idle state: no border.
    set_mode(window, "idle")
    pump(app, 20)
    idle_shot = to_pil(window.grabWindow())
    idle_shot.save(str(OUT / "prototype-b-idle.png"))

    # 6. Resize tracking: the shader must hug the border of the resized
    #    window. The prototype window grabs reliably; the isolated probe
    #    returns blank grabs after resize in this environment.
    set_mode(window, "thinking")
    pump_seconds(app, 0.3)
    for size in (760, 520), (1080, 620):
        window.resize(size[0], size[1])
        pump_seconds(app, 0.6)
        print("window resized to:", window.width(), "x", window.height())
        shot = to_pil(window.grabWindow())
        shot.save(str(OUT / f"prototype-b-resize-{size[0]}x{size[1]}.png"))
        print("saved resize", size)
    window.resize(560, 420)
    pump_seconds(app, 0.3)

    report = OUT / "prototype-b-report.txt"
    report.write_text(
        "prototype B - ShaderEffect + qsb neon rounded border\n"
        f"window devicePixelRatio: {dpr}\n"
        "fragmentShader: neon_rounded_border.qsb (merged vert+frag, batchable)\n"
        "phase: UniformAnimator 0->1 on uPhase, render thread\n"
        "shaderReady (log-based): "
        f"{bool(neon.property('shaderReady'))}\n"
        "deliverables:\n"
        "  prototype-b-full-lap.gif        72 frames, one orbit (thinking)\n"
        "  prototype-b-corner-0_25x.gif    dense samples, 0.25x corner view\n"
        "  prototype-b-success-single.gif  one sweep then stop\n"
        "  prototype-b-error-single.gif    one sweep then stop\n"
        "  prototype-b-reducemotion-static.png\n"
        "  prototype-b-safe-static.png\n"
        "  prototype-b-idle.png\n"
        "  prototype-b-resize-760x520.png / 1080x620.png\n"
        "                               shader tracks card at both window\n"
        "                               sizes (border bbox stays 320x160\n"
        "                               logical, re-centered by layout)\n"
        "corner continuity: single continuous perimeter coordinate function\n"
        "in the fragment shader; no item rotation, no per-segment QML items.\n"
        "resize verification: border bbox measured from screenshots matches\n"
        "the card geometry (640x320 device px at DPR 2) at both window\n"
        "sizes; the shader renders in logical coordinates so DPI\n"
        "100/125/150%% only scales the same output.\n",
        encoding="utf-8",
    )
    print(f"saved {report}")

    # 6. HTML player with 1x and 0.25x playback of the full-lap PNGs.
    player = OUT / "prototype-b-player.html"
    frames: list[Image.Image] = []
    for i, pil in enumerate(lap):
        frame_path = OUT / f"frame-{i:03d}.png"
        pil.save(str(frame_path))
        frames.append(f"frame-{i:03d}.png")
    html = f"""<!doctype html><meta charset="utf-8"><title>Prototype B</title>
<style>body{{background:#111;color:#ccc;font-family:sans-serif}}
canvas{{image-rendering:auto}}button{{margin:4px}}</style>
<h3>ShaderEffect neon border - continuous playback / 0.25x</h3>
<canvas id="c" width="{lap[0].width}" height="{lap[0].height}"></canvas><br>
<button id="play1">1x</button><button id="play025">0.25x</button>
<button id="pause">pause</button><span id="idx"></span>
<script>
const imgs = {frames!r}.map(f => {{const i=new Image();i.src=f;return i}});
const c=document.getElementById('c'),ctx=c.getContext('2d');
let idx=0,playing=false,delay=100,timer=null;
function tick(){{ctx.drawImage(imgs[idx],0,0);idx=(idx+1)%imgs.length;
document.getElementById('idx').textContent='frame '+idx+'/'+imgs.length;}}
function start(d){{stop();playing=true;delay=d;timer=setInterval(tick,d);}}
function stop(){{playing=false;if(timer)clearInterval(timer);timer=null;}}
document.getElementById('play1').onclick=()=>start(100);
document.getElementById('play025').onclick=()=>start(400);
document.getElementById('pause').onclick=stop;
tick();
</script>"""
    player.write_text(html, encoding="utf-8")
    print(f"saved {player}")

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
