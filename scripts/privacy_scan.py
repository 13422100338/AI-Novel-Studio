from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
}
EXCLUDED_FILES = {".privacy-blocklist"}
HOME_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"),
    re.compile(r"/(?:Users|home)/[^/\s]+"),
)


@dataclass(frozen=True)
class Finding:
    path: Path
    kind: str
    value: str


def load_terms(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise ValueError(f"privacy terms file is missing: {path}")
    terms = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not terms:
        raise ValueError(f"privacy terms file contains no privacy terms: {path}")
    return terms


def scan_tree(root: Path, terms: tuple[str, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.name in EXCLUDED_FILES
            or any(part in EXCLUDED_DIRS for part in path.parts)
        ):
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="ignore")
        for term in terms:
            if term.encode("utf-8") in raw:
                findings.append(Finding(path, "private-term", term))
        for pattern in HOME_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(Finding(path, "home-path", match.group(0)))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--terms-file", type=Path)
    parser.add_argument("--require-terms", action="store_true")
    args = parser.parse_args()

    terms: tuple[str, ...] = ()
    if args.terms_file:
        terms = load_terms(args.terms_file)
    elif args.require_terms:
        raise ValueError("privacy terms file is required for release verification")

    findings = scan_tree(args.root, terms)
    for finding in findings:
        print(f"{finding.kind}: {finding.path}: {finding.value}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
