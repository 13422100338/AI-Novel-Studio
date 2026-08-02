import logging
import sys
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.logging_config import PrivacyFormatter
from ai_novel_studio.infrastructure.privacy.redaction import (
    redact_credentials,
    redact_private_paths,
)


def test_redact_private_paths_replaces_explicit_home() -> None:
    private_home = "C:" + "\\Users\\" + "private-user"
    text = f"failed to open {private_home}\\Novel\\chapter.md"

    assert redact_private_paths(text, Path(private_home)) == (
        r"failed to open <USER_HOME>\Novel\chapter.md"
    )


def test_privacy_formatter_redacts_log_record() -> None:
    formatter = PrivacyFormatter("%(levelname)s %(message)s")
    private_home = "C:" + "\\Users\\" + "private-user"
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        f"problem at {private_home}\\draft.md",
        (),
        None,
    )

    rendered = formatter.format(record)

    assert "private-user" not in rendered
    assert "<USER_HOME>" in rendered


def test_privacy_formatter_redacts_api_key_from_traceback() -> None:
    formatter = PrivacyFormatter("%(levelname)s %(message)s")
    try:
        raise RuntimeError("provider echoed sk-live-sensitive")
    except RuntimeError:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "model task failed",
            (),
            sys.exc_info(),
        )

    rendered = formatter.format(record)

    assert "sk-live-sensitive" not in rendered
    assert "<REDACTED_CREDENTIAL>" in rendered
    assert "Traceback" in rendered


@pytest.mark.parametrize(
    ("text", "secret", "expected"),
    (
        (
            '"api_key": "secretvalue123"',
            "secretvalue123",
            '"api_key": "<REDACTED_CREDENTIAL>"',
        ),
        (
            '"authorization": "Bearer bearerToken123"',
            "bearerToken123",
            '"authorization": "<REDACTED_CREDENTIAL>"',
        ),
        (
            "'access_token' = 'accessToken123'",
            "accessToken123",
            "'access_token' = '<REDACTED_CREDENTIAL>'",
        ),
        (
            "Authorization: Basic dXNlcjpwYXNz",
            "dXNlcjpwYXNz",
            "Authorization: <REDACTED_CREDENTIAL>",
        ),
        (
            "Authorization: Bearer bearerToken123",
            "bearerToken123",
            "Authorization: <REDACTED_CREDENTIAL>",
        ),
        (
            "api_key=plainSecret123",
            "plainSecret123",
            "api_key=<REDACTED_CREDENTIAL>",
        ),
        (
            "access_token: accessToken123",
            "accessToken123",
            "access_token: <REDACTED_CREDENTIAL>",
        ),
        (
            "provider echoed sk-live-sensitive",
            "sk-live-sensitive",
            "provider echoed <REDACTED_CREDENTIAL>",
        ),
        (
            "provider echoed AIzaSyDUMMYVALUE1234567890",
            "AIzaSyDUMMYVALUE1234567890",
            "provider echoed <REDACTED_CREDENTIAL>",
        ),
        (
            "request used Bearer standaloneToken123",
            "standaloneToken123",
            "request used Bearer <REDACTED_CREDENTIAL>",
        ),
    ),
)
def test_redact_credentials_supports_bounded_common_forms(
    text: str,
    secret: str,
    expected: str,
) -> None:
    rendered = redact_credentials(text)

    assert rendered == expected
    assert secret not in rendered


def test_redact_credentials_preserves_following_fields_and_lines() -> None:
    text = "api_key=plainSecret123 status=500\nmessage=connection failed"

    rendered = redact_credentials(text)

    assert rendered == (
        "api_key=<REDACTED_CREDENTIAL> status=500\nmessage=connection failed"
    )
