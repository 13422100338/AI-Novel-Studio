"""WebEngine entry alias (compatibility for Phase 1 documentation commands).

The unified default entry now lives in ``ai_novel_studio.ui_qml.bootstrap``;
this module keeps the previously documented command working unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_novel_studio.ui_qml.bootstrap import main as _bootstrap_main


def main(argv: Sequence[str] | None = None) -> int:
    return _bootstrap_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
