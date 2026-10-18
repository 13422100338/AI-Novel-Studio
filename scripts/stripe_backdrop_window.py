r"""Standalone striped backdrop window for deterministic DWM backdrop evidence.

Creates a full-screen opaque PySide6 window painted with high-contrast
vertical stripes and runs for N seconds. It must be started BEFORE the
Native Glass Lab windowed capture: the lab window is raised afterwards, so
DWM samples the stripe window through Desktop Acrylic.

If the DWM backdrop really blurs window-behind content:
  - native acrylic composed evidence shows blurred stripe colors;
  - native mica does NOT (Mica samples wallpaper/theme, not windows behind);
  - solid composed evidence stays opaque theme color.

Usage (from the worktree root, using its venv):
    .\.venv\Scripts\python.exe scripts\stripe_backdrop_window.py --seconds 600
    .\.venv\Scripts\python.exe scripts\stripe_backdrop_window.py --seconds 15
        --probe-out docs\frontend\screenshots\stripe-probe.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

_STRIPES = (
    (229, 57, 53),    # red
    (0, 188, 212),    # cyan
    (253, 216, 53),   # yellow
    (30, 136, 229),   # blue
)
_STRIPE_W = 96
_SPLIT = "--split" in sys.argv


class StripeBackdrop(QWidget):
    """Full-screen opaque window with vertical color stripes."""

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        try:
            if _SPLIT:
                # Two halves: left red, right cyan. Moving the lab window
                # across the halves must change its acrylic background color
                # when the DWM material really samples window-behind content.
                half = self.width() // 2
                painter.fillRect(0, 0, half, self.height(), QColor(229, 57, 53))
                painter.fillRect(
                    half, 0, self.width() - half, self.height(),
                    QColor(0, 188, 212),
                )
            else:
                painter.fillRect(self.rect(), QColor(20, 20, 20))
                index = 0
                left = 0
                while left < self.width():
                    r, g, b = _STRIPES[index % len(_STRIPES)]
                    right = min(left + _STRIPE_W, self.width())
                    painter.fillRect(
                        left, 0, right - left, self.height(), QColor(r, g, b)
                    )
                    left = right
                    index += 1
        finally:
            painter.end()


def main() -> int:
    seconds = 120
    if "--seconds" in sys.argv:
        seconds = int(sys.argv[sys.argv.index("--seconds") + 1])

    app = QApplication(sys.argv)
    widget = StripeBackdrop()
    widget.setWindowTitle("StripeBackdrop")
    widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
    widget.setWindowFlags(
        Qt.FramelessWindowHint
        | Qt.Tool
        | Qt.WindowDoesNotAcceptFocus
        | Qt.WindowStaysOnTopHint
    )
    widget.showFullScreen()
    widget.raise_()

    if "--probe-out" in sys.argv:
        time.sleep(1.5)
        image = widget.grab().toImage()
        out = Path(sys.argv[sys.argv.index("--probe-out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        assert image.save(str(out)), f"failed to save {out}"
        mid = image.height() // 2
        colors: list[str] = []
        for x in range(8, image.width(), _STRIPE_W):
            colors.append(image.pixelColor(x, mid).name())
        distinct = sorted(set(colors))
        print(
            f"probe saved {out} {image.width()}x{image.height()}, "
            f"mid-row distinct colors={len(distinct)}: {distinct[:8]}",
            flush=True,
        )

    print(
        f"stripe window covering {widget.width()}x{widget.height()}, "
        f"running {seconds}s",
        flush=True,
    )
    QTimer.singleShot(seconds * 1000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
