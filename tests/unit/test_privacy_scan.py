from pathlib import Path

import pytest

from scripts.privacy_scan import load_terms, scan_tree


def test_load_terms_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text("# private\nPrivate Person\n\nprivate-user\n", encoding="utf-8")

    assert load_terms(terms_file) == ("Private Person", "private-user")


def test_scan_tree_detects_private_term_and_home_path(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    private_home = "C:" + "\\Users\\" + "private-user"
    source.write_text(
        f"Author: Private Person\nPath: {private_home}\\draft.md\n",
        encoding="utf-8",
    )

    findings = scan_tree(tmp_path, ("Private Person",))

    assert {finding.kind for finding in findings} == {"private-term", "home-path"}


def test_scan_tree_ignores_local_privacy_blocklist(tmp_path: Path) -> None:
    (tmp_path / ".privacy-blocklist").write_text("Private Person\n", encoding="utf-8")

    assert scan_tree(tmp_path, ("Private Person",)) == []


def test_scan_tree_ignores_python_cache_directories(tmp_path: Path) -> None:
    cache_dir = tmp_path / "scripts" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "module.pyc").write_bytes(b"Private Person")

    assert scan_tree(tmp_path, ("Private Person",)) == []


def test_load_terms_rejects_missing_or_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="privacy terms"):
        load_terms(tmp_path / "missing.txt")

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("# no terms\n", encoding="utf-8")
    with pytest.raises(ValueError, match="privacy terms"):
        load_terms(empty_file)
