from __future__ import annotations

import re
from pathlib import Path

WINDOWS_HOME = re.compile(r"[A-Za-z]:\\Users\\[^\\/\s]+", re.IGNORECASE)
POSIX_HOME = re.compile(r"/(?:Users|home)/[^/\s]+")


def redact_private_paths(text: str, home: Path | None = None) -> str:
    rendered = text
    if home is not None:
        home_text = str(home)
        rendered = rendered.replace(home_text, "<USER_HOME>")
        rendered = rendered.replace(home_text.replace("\\", "/"), "<USER_HOME>")
    rendered = WINDOWS_HOME.sub("<USER_HOME>", rendered)
    return POSIX_HOME.sub("<USER_HOME>", rendered)
