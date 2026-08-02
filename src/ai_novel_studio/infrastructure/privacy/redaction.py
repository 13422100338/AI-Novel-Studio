from __future__ import annotations

import re
from pathlib import Path

WINDOWS_HOME = re.compile(r"[A-Za-z]:\\Users\\[^\\/\s]+", re.IGNORECASE)
POSIX_HOME = re.compile(r"/(?:Users|home)/[^/\s]+")
API_KEY = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{4,}|AIza[A-Za-z0-9_-]{20,})\b",
    re.IGNORECASE,
)
BEARER_CREDENTIAL = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/\-=]{8,}",
    re.IGNORECASE,
)
LABELED_CREDENTIAL = re.compile(
    r"(\b(?:api[_ -]?key|authorization|access[_ -]?token)\b\s*[:=]\s*)"
    r"(?:Bearer\s+)?[^\s,;]+",
    re.IGNORECASE,
)


def redact_private_paths(text: str, home: Path | None = None) -> str:
    rendered = text
    if home is not None:
        home_text = str(home)
        rendered = rendered.replace(home_text, "<USER_HOME>")
        rendered = rendered.replace(home_text.replace("\\", "/"), "<USER_HOME>")
    rendered = WINDOWS_HOME.sub("<USER_HOME>", rendered)
    return POSIX_HOME.sub("<USER_HOME>", rendered)


def redact_credentials(text: str) -> str:
    rendered = API_KEY.sub("<REDACTED_CREDENTIAL>", text)
    rendered = BEARER_CREDENTIAL.sub("Bearer <REDACTED_CREDENTIAL>", rendered)
    return LABELED_CREDENTIAL.sub(
        r"\1<REDACTED_CREDENTIAL>",
        rendered,
    )
