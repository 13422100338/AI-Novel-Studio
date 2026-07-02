import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.infrastructure.storage.project_layout import ProjectLayout


class ProjectLock:
    def __init__(self, layout: ProjectLayout) -> None:
        self.path = layout.pipeline / "writer.lock"
        self._acquired = False

    def acquire(self) -> None:
        if self._acquired:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            raise RuntimeError("project is already open for writing") from exc
        try:
            payload = {"pid": os.getpid(), "created_at": datetime.now(UTC).isoformat()}
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            self.path.unlink(missing_ok=True)
            raise
        self._acquired = True

    def release(self) -> None:
        if self._acquired:
            self.path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
