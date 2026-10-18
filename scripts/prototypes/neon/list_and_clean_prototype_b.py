"""List and (optionally) clean the prototype-b capture output directory."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> int:
    target = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "docs"
        / "frontend"
        / "screenshots"
        / "prototype-b"
    )
    allowed_root = Path(__file__).resolve().parent.parent.parent.parent
    print("target:", target)
    print("exists:", target.is_dir())
    if target.is_dir():
        names = sorted(p.name for p in target.iterdir())
        print("count:", len(names))
        for name in names[:10]:
            print(name)
    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        if not target.is_dir():
            print("nothing to clean")
            return 0
        if target.resolve().is_relative_to(allowed_root.resolve()):
            shutil.rmtree(target)
            print("removed:", target)
        else:
            print("refusing to remove outside allowed root")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
