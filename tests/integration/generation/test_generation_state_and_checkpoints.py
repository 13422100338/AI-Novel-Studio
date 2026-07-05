from pathlib import Path

import pytest

from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.checkpoint_repository import (
    CheckpointContentError,
    CheckpointIntegrityError,
    CheckpointRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import (
    ActiveGenerationError,
    GenerationRepository,
    GenerationStateError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "生成状态测试")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "测试章", "1")
    runs = GenerationRepository(project)
    checkpoints = CheckpointRepository(project, runs)
    return project, chapter, runs, checkpoints


def _preparing(runs: GenerationRepository, chapter_id: str):  # type: ignore[no-untyped-def]
    return runs.create_preparing(
        chapter_id=chapter_id,
        mode=CreationMode.BASIC,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider-1",
        model_id="writer-1",
        output_token_limit=16_000,
        prompt_version="prose-v1",
    )


def _ready(project, runs, run):  # type: ignore[no-untyped-def]
    manifest = ContextManifest(
        create_manifest_id(),
        run.chapter_id,
        run.id,
        100_000,
        run.output_token_limit,
        0,
        (),
        (),
        (),
        utc_now(),
    )
    ContextManifestRepository(project).save(manifest)
    return runs.transition(
        run.id,
        GenerationStatus.PREPARING,
        GenerationStatus.READY,
        context_manifest_id=manifest.id,
    )


def _streaming(project, runs, chapter_id):  # type: ignore[no-untyped-def]
    ready = _ready(project, runs, _preparing(runs, chapter_id))
    return runs.transition(ready.id, GenerationStatus.READY, GenerationStatus.STREAMING)


def test_repository_enforces_legal_transitions_and_records_fields(tmp_path: Path) -> None:
    project, chapter, runs, _ = _workspace(tmp_path)
    streaming = _streaming(project, runs, chapter.id)

    completed = runs.transition(
        streaming.id,
        GenerationStatus.STREAMING,
        GenerationStatus.COMPLETED,
        input_tokens=1200,
        output_tokens=800,
        cached_input_tokens=600,
        reasoning_tokens=100,
    )
    accepted = runs.transition(
        completed.id,
        GenerationStatus.COMPLETED,
        GenerationStatus.ACCEPTED,
        accepted_chapter_revision=3,
    )

    assert completed.completed_at is not None
    assert completed.output_tokens == 800
    assert accepted.status == GenerationStatus.ACCEPTED
    assert accepted.accepted_at is not None
    assert accepted.accepted_chapter_revision == 3


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (GenerationStatus.PREPARING, GenerationStatus.FAILED),
        (GenerationStatus.READY, GenerationStatus.FAILED),
        (GenerationStatus.STREAMING, GenerationStatus.PARTIAL),
        (GenerationStatus.STREAMING, GenerationStatus.FAILED),
        (GenerationStatus.PARTIAL, GenerationStatus.ACCEPTED),
        (GenerationStatus.PARTIAL, GenerationStatus.DISCARDED),
        (GenerationStatus.COMPLETED, GenerationStatus.DISCARDED),
    ],
)
def test_remaining_legal_transitions(
    tmp_path: Path,
    start: GenerationStatus,
    target: GenerationStatus,
) -> None:
    project, chapter, runs, _ = _workspace(tmp_path)
    run = _preparing(runs, chapter.id)
    if start in {
        GenerationStatus.READY,
        GenerationStatus.STREAMING,
        GenerationStatus.PARTIAL,
        GenerationStatus.COMPLETED,
    }:
        run = _ready(project, runs, run)
    if start in {
        GenerationStatus.STREAMING,
        GenerationStatus.PARTIAL,
        GenerationStatus.COMPLETED,
    }:
        run = runs.transition(run.id, GenerationStatus.READY, GenerationStatus.STREAMING)
    if start == GenerationStatus.PARTIAL:
        run = runs.transition(
            run.id, GenerationStatus.STREAMING, GenerationStatus.PARTIAL
        )
    if start == GenerationStatus.COMPLETED:
        run = runs.transition(
            run.id, GenerationStatus.STREAMING, GenerationStatus.COMPLETED
        )

    fields: dict[str, object] = {}
    if target == GenerationStatus.FAILED:
        fields = {"failure_code": "TEST", "failure_message": "测试失败"}
    elif target == GenerationStatus.ACCEPTED:
        fields = {"accepted_chapter_revision": 3}
    changed = runs.transition(run.id, start, target, **fields)

    assert changed.status == target


def test_illegal_or_stale_transition_is_rejected(tmp_path: Path) -> None:
    project, chapter, runs, _ = _workspace(tmp_path)
    ready = _ready(project, runs, _preparing(runs, chapter.id))

    with pytest.raises(GenerationStateError, match="非法"):
        runs.transition(ready.id, GenerationStatus.READY, GenerationStatus.COMPLETED)
    with pytest.raises(GenerationStateError, match="状态已变化"):
        runs.transition(ready.id, GenerationStatus.PREPARING, GenerationStatus.FAILED)
    with pytest.raises(ValueError, match="不支持的更新字段"):
        runs.transition(
            ready.id,
            GenerationStatus.READY,
            GenerationStatus.STREAMING,
            model_id="偷偷换模型",
        )


def test_only_one_active_writer_is_allowed_per_chapter(tmp_path: Path) -> None:
    _, chapter, runs, _ = _workspace(tmp_path)
    first = _preparing(runs, chapter.id)

    with pytest.raises(ActiveGenerationError, match="已有活动"):
        _preparing(runs, chapter.id)

    runs.transition(
        first.id,
        GenerationStatus.PREPARING,
        GenerationStatus.FAILED,
        failure_code="STOPPED",
        failure_message="结束测试",
    )
    assert _preparing(runs, chapter.id).status == GenerationStatus.PREPARING


def test_checkpoints_are_cumulative_unique_and_never_overwrite_history(
    tmp_path: Path,
) -> None:
    project, chapter, runs, checkpoints = _workspace(tmp_path)
    run = _streaming(project, runs, chapter.id)

    first = checkpoints.append(run.id, "第一段")
    second = checkpoints.append(run.id, "第一段\n第二段", finish_reason="length")

    assert first.sequence == 0 and second.sequence == 1
    assert first.text_path != second.text_path
    assert checkpoints.read(first.id) == "第一段"
    assert checkpoints.read(second.id) == "第一段\n第二段"
    assert checkpoints.latest(run.id) == second


def test_non_cumulative_or_empty_checkpoint_is_rejected_and_previous_survives(
    tmp_path: Path,
) -> None:
    project, chapter, runs, checkpoints = _workspace(tmp_path)
    run = _streaming(project, runs, chapter.id)
    first = checkpoints.append(run.id, "不可丢失的第一段")

    with pytest.raises(CheckpointContentError, match="累计"):
        checkpoints.append(run.id, "替换文本")
    with pytest.raises(CheckpointContentError, match="不能为空"):
        checkpoints.append(run.id, "")

    assert checkpoints.latest(run.id) == first
    assert checkpoints.read(first.id) == "不可丢失的第一段"


def test_atomic_write_failure_rolls_back_new_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, chapter, runs, checkpoints = _workspace(tmp_path)
    run = _streaming(project, runs, chapter.id)
    first = checkpoints.append(run.id, "第一段")

    def fail_write(_path: Path, _text: str) -> None:
        raise OSError("磁盘写入失败")

    monkeypatch.setattr(
        "ai_novel_studio.infrastructure.storage.checkpoint_repository.atomic_write_text",
        fail_write,
    )
    with pytest.raises(OSError, match="磁盘写入失败"):
        checkpoints.append(run.id, "第一段\n第二段")

    assert checkpoints.latest(run.id) == first
    with project.database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM generation_checkpoints WHERE run_id = ?", (run.id,)
        ).fetchone()[0]
    assert count == 1


def test_preexisting_checkpoint_path_is_never_deleted(tmp_path: Path) -> None:
    project, chapter, runs, checkpoints = _workspace(tmp_path)
    run = _streaming(project, runs, chapter.id)
    path = (
        project.layout.pipeline
        / "checkpoints"
        / f"run_{run.id}"
        / "checkpoint_0.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("磁盘上已有的内容", encoding="utf-8")

    with pytest.raises(FileExistsError, match="已存在"):
        checkpoints.append(run.id, "新内容")

    assert path.read_text(encoding="utf-8") == "磁盘上已有的内容"


def test_checkpoint_read_rejects_path_traversal_and_hash_mismatch(tmp_path: Path) -> None:
    project, chapter, runs, checkpoints = _workspace(tmp_path)
    run = _streaming(project, runs, chapter.id)
    checkpoint = checkpoints.append(run.id, "可信正文")

    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE generation_checkpoints SET text_path = ? WHERE id = ?",
            ("../outside.md", checkpoint.id),
        )
    with pytest.raises(CheckpointIntegrityError, match="项目目录"):
        checkpoints.read(checkpoint.id)

    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE generation_checkpoints SET text_path = ? WHERE id = ?",
            (checkpoint.text_path, checkpoint.id),
        )
    path = project.layout.root / checkpoint.text_path
    path.write_text("被篡改", encoding="utf-8")
    with pytest.raises(CheckpointIntegrityError, match="哈希"):
        checkpoints.latest(run.id)
