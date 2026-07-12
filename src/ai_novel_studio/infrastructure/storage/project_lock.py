import json
import os
import signal
from datetime import UTC, datetime
from typing import Any

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
            if self._recover_stale_lock():
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            else:
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

    def _recover_stale_lock(self) -> bool:
        payload = self._read_lock_payload()
        pid = payload.get("pid")
        if not isinstance(pid, int) or _process_is_running(pid):
            return False
        self.path.unlink(missing_ok=True)
        return True

    def _read_lock_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

    def release(self) -> None:
        if self._acquired:
            self.path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, signal.Signals(0))
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_is_running(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
