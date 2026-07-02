import hashlib
import json
from pathlib import Path
from typing import Any

from ai_novel_studio.application.legacy_import.docx_reader import (
    LegacyDocumentError,
    read_docx_text,
)
from ai_novel_studio.application.legacy_import.models import (
    LegacyChapter,
    LegacyVolume,
    MigrationIssue,
    MigrationPreview,
)


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


class LegacyProjectScanner:
    def scan(self, root: Path) -> MigrationPreview:
        source_root = root.resolve()
        meta_path = source_root / "meta.json"
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("legacy meta.json is missing or invalid") from exc
        if not isinstance(raw, dict):
            raise ValueError("legacy meta.json root must be an object")

        issues: list[MigrationIssue] = []
        volumes: list[LegacyVolume] = []
        for volume_index, volume_data in enumerate(_list_of_dicts(raw.get("volumes"))):
            title = str(volume_data.get("name") or f"未命名卷 {volume_index + 1}")
            chapters: list[LegacyChapter] = []
            for chapter_index, chapter_data in enumerate(
                _list_of_dicts(volume_data.get("chapters"))
            ):
                chapter_title = str(
                    chapter_data.get("name") or f"未命名章 {chapter_index + 1}"
                )
                relative = Path(title) / f"{chapter_title}.docx"
                document_path = source_root / relative
                source_hash: str | None = None
                if not document_path.is_file():
                    issues.append(
                        MigrationIssue(
                            "document_missing", "legacy chapter document is missing", relative.as_posix()
                        )
                    )
                else:
                    try:
                        read_docx_text(document_path)
                        source_hash = hashlib.sha256(document_path.read_bytes()).hexdigest()
                    except (LegacyDocumentError, OSError):
                        issues.append(
                            MigrationIssue(
                                "document_corrupt", "legacy chapter document is unreadable",
                                relative.as_posix(),
                            )
                        )
                chapters.append(
                    LegacyChapter(
                        title=chapter_title,
                        synopsis=str(chapter_data.get("synopsis") or ""),
                        ai_synopsis=str(chapter_data.get("ai_synopsis") or ""),
                        declared_number=str(chapter_data.get("number") or chapter_index + 1),
                        source=relative.as_posix(),
                        source_hash=source_hash,
                    )
                )
            volumes.append(
                LegacyVolume(
                    title=title,
                    synopsis=str(volume_data.get("synopsis") or ""),
                    chapters=tuple(chapters),
                )
            )
        return MigrationPreview(
            source_root=source_root,
            title=str(raw.get("title") or source_root.name),
            global_synopsis=str(raw.get("global_synopsis") or ""),
            characters=tuple(_list_of_dicts(raw.get("characters"))),
            volumes=tuple(volumes),
            issues=tuple(issues),
        )
