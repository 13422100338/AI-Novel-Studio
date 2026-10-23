"""Explicit project-scoped note writes; never a manuscript write capability."""

from collections.abc import Callable
from threading import Lock

from ai_novel_studio.domain.author_note import AuthorNote
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

NOTE_WRITE_TOOLS = ("create_novel_note", "update_novel_note")


class NovelNoteService:
    def __init__(
        self, project: ProjectRepository, *, on_saved: Callable[[str], None] | None = None
    ) -> None:
        self.project_id = project.project.id
        self.repository = NoteRepository(project)
        self._on_saved = on_saved
        self._lock = Lock()
        self._closed = False

    def revoke(self) -> None:
        with self._lock:
            self._closed = True

    def _check(self) -> None:
        if self._closed:
            raise ValueError("小说项目已切换，旧笔记写工具已失效")

    def _notify(self, identity: str) -> None:
        if self._on_saved:
            try:
                self._on_saved(identity)
            except RuntimeError:
                # The GUI may already be destroyed; the committed note remains saved.
                pass

    def create(self, title: str, content: str, kind: str = "OTHER") -> AuthorNote:
        with self._lock:
            self._check()
            note = self.repository.create(title, content, kind=kind)
        self._notify(note.id)
        return note

    def update(
        self,
        identity: str,
        expected_revision: int,
        content: str,
        title: str | None = None,
        kind: str | None = None,
    ) -> AuthorNote:
        with self._lock:
            self._check()
            note = self.repository.save(
                identity, content, expected_revision=expected_revision, title=title, kind=kind
            )
        self._notify(note.id)
        return note
