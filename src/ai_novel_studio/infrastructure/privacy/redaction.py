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
_CREDENTIAL_LABEL = r"(?:api[_ -]?key|authorization|access[_ -]?token)"
QUOTED_LABELED_CREDENTIAL = re.compile(
    rf"(?P<prefix>(?P<label_quote>[\"']?){_CREDENTIAL_LABEL}"
    r"(?P=label_quote)\s*[:=]\s*)"
    r"(?P<value_quote>[\"'])[^\"'\r\n]*(?P=value_quote)",
    re.IGNORECASE,
)
AUTHORIZATION_SCHEME_CREDENTIAL = re.compile(
    r"(?P<prefix>(?P<label_quote>[\"']?)authorization"
    r"(?P=label_quote)\s*[:=]\s*)"
    r"(?:Basic|Bearer)[ \t]+[^\s,;}\]\"']+",
    re.IGNORECASE,
)
LABELED_CREDENTIAL = re.compile(
    rf"(?P<prefix>(?P<label_quote>[\"']?){_CREDENTIAL_LABEL}"
    r"(?P=label_quote)\s*[:=]\s*)"
    r"[^\s,;}\]\"']+",
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
    rendered = QUOTED_LABELED_CREDENTIAL.sub(_redact_quoted_credential, text)
    rendered = AUTHORIZATION_SCHEME_CREDENTIAL.sub(
        r"\g<prefix><REDACTED_CREDENTIAL>",
        rendered,
    )
    rendered = LABELED_CREDENTIAL.sub(
        r"\g<prefix><REDACTED_CREDENTIAL>",
        rendered,
    )
    rendered = API_KEY.sub("<REDACTED_CREDENTIAL>", rendered)
    rendered = BEARER_CREDENTIAL.sub("Bearer <REDACTED_CREDENTIAL>", rendered)
    return rendered


def _redact_quoted_credential(match: re.Match[str]) -> str:
    quote = match.group("value_quote")
    return (
        f"{match.group('prefix')}{quote}"
        f"<REDACTED_CREDENTIAL>{quote}"
    )
