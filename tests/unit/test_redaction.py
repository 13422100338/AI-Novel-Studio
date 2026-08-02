import logging
import sys
from pathlib import Path

from ai_novel_studio.infrastructure.logging_config import PrivacyFormatter
from ai_novel_studio.infrastructure.privacy.redaction import redact_private_paths


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
