"""Remove binary/temporary debug artifacts from the neon prototype folder.

Only deletes files that are clearly session-generated debug output (png
grabs, probe qsb/qml, coverage images). Keeps all prototype sources and
capture scripts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEBUG_PREFIXES = (
    "debug-",
    "_coverage_probe",
    "_iso_probe",
)
DEBUG_EXACT = (
    "debug-minimal.png",
    "debug-coverage.png",
    "debug_minimal_frag.qsb",
    "debug_uniform_animator_frag.qsb",
)


def main() -> int:
    removed = []
    for p in ROOT.iterdir():
        name = p.name
        if name in DEBUG_EXACT or name.startswith(DEBUG_PREFIXES):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(name)
    print("removed:", removed)
    print("remaining:", sorted(x.name for x in ROOT.iterdir()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
