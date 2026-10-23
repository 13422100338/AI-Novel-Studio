"""Bounded, append-only note revisions. No novel database migrations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from ai_novel_studio.domain.author_note import (
    NOTE_KINDS,
    AuthorNote,
    canonical,
    note_hash,
    note_id,
    validate_note_text,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REVISION = re.compile(rf"^({_UUID})\.([0-9]{{8}})\.json$")
_TEMP = re.compile(rf"^\.({_UUID})\.([0-9]{{8}})\.([0-9a-f]{{32}})\.tmp$")
_FIELDS = {
    "schema_version",
    "project_id",
    "note_id",
    "revision",
    "title",
    "kind",
    "content",
    "source_hash",
    "previous_revision_hash",
    "created_at",
}
_GUARD = Lock()
_LOCKS: dict[Path, Lock] = {}
_MAX_FILE = 1_048_576


class NoteRecoveryRequired(ValueError):
    pass


def _regular(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("笔记目录包含软链接或重解析点")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("笔记中包含非普通文件")


class NoteRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project_id = project.project.id
        self.root = project.layout.root.resolve()
        self.directory = self.root / "notes"

    def _payload(self, path: Path, identity: str, revision: int) -> tuple[dict[str, Any], bytes]:
        _regular(path)
        if path.stat().st_size > _MAX_FILE:
            raise ValueError("笔记文件超过安全读取上限，未截断")
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict) or set(value) != _FIELDS or canonical(value) != raw:
                raise ValueError
            if (
                type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["project_id"] != self.project_id
                or value["note_id"] != identity
                or type(value["revision"]) is not int
                or value["revision"] != revision
                or not 1 <= revision <= 2000
                or value["kind"] not in NOTE_KINDS
            ):
                raise ValueError
            note_id(identity)
            validate_note_text(value["title"], title=True)
            validate_note_text(value["content"])
            if value["source_hash"] != note_hash(value["content"]):
                raise ValueError
            stamp = datetime.fromisoformat(value["created_at"])
            if (
                stamp.utcoffset() != UTC.utcoffset(stamp)
                or stamp.isoformat(timespec="microseconds") != value["created_at"]
            ):
                raise ValueError
            previous = value["previous_revision_hash"]
            if previous is not None and (
                not isinstance(previous, str) or not re.fullmatch("[0-9a-f]{64}", previous)
            ):
                raise ValueError
            return value, raw
        except (TypeError, ValueError, KeyError, UnicodeError) as exc:
            raise ValueError("笔记修订损坏或身份不匹配；原文件保留") from exc

    @staticmethod
    def _note(value: dict[str, Any]) -> AuthorNote:
        return AuthorNote(
            value["note_id"],
            value["title"],
            value["kind"],
            value["revision"],
            value["content"],
            value["source_hash"],
            value["created_at"],
        )

    def _scan(self) -> tuple[dict[str, list[tuple[dict[str, Any], bytes]]], list[str]]:
        if not self.directory.exists():
            if self.directory.is_symlink():
                raise ValueError("笔记目录不能是软链接")
            return {}, []
        _regular(self.directory, directory=True)
        groups: dict[str, list[tuple[int, Path]]] = {}
        temps: list[str] = []
        count = total = 0
        for path in self.directory.iterdir():
            count += 1
            if count > 10033:
                raise ValueError("笔记扫描文件数超限，未省略资料")
            _regular(path)
            size = path.stat().st_size
            if size > _MAX_FILE:
                raise ValueError("笔记文件过大")
            total += size
            if total > 64 * 1024 * 1024:
                raise ValueError("笔记修订总量超限，请先导出归档")
            if path.name == ".write.lock":
                if size > 1:
                    raise ValueError("笔记保存锁异常")
                continue
            match = _REVISION.fullmatch(path.name)
            if match:
                groups.setdefault(match[1], []).append((int(match[2]), path))
            elif _TEMP.fullmatch(path.name):
                temps.append(path.name)
            else:
                raise ValueError("笔记目录有无法识别的文件；未删除或覆盖")
        if len(groups) > 200 or len(temps) > 32 or sum(map(len, groups.values())) > 10000:
            raise ValueError("笔记或修订数量超限，未截断")
        result = {}
        for identity, revisions in groups.items():
            if len(revisions) > 2000:
                raise ValueError("单篇笔记修订数量超限")
            chain = []
            previous = None
            for expected, (number, path) in enumerate(sorted(revisions), 1):
                if number != expected:
                    raise ValueError("笔记修订链缺号，未回退旧版")
                value, raw = self._payload(path, identity, number)
                if value["previous_revision_hash"] != previous:
                    raise ValueError("笔记历史哈希链不一致")
                chain.append((value, raw))
                previous = hashlib.sha256(raw).hexdigest()
            result[identity] = chain
        return result, temps

    def list_notes(self) -> tuple[AuthorNote, ...]:
        groups, _ = self._scan()
        return tuple(
            sorted(
                (self._note(v[-1][0]) for v in groups.values()), key=lambda n: (n.created_at, n.id)
            )
        )

    def read(self, identity: str, *, revision: int | None = None) -> AuthorNote:
        note_id(identity)
        groups, _ = self._scan()
        if identity not in groups:
            raise ValueError("笔记不存在")
        chain = groups[identity]
        if revision is not None and (type(revision) is not int or not 1 <= revision <= len(chain)):
            raise ValueError("笔记修订不存在")
        return self._note(chain[-1 if revision is None else revision - 1][0])

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        self.directory.mkdir(exist_ok=True)
        _regular(self.directory, directory=True)
        with _GUARD:
            lock = _LOCKS.setdefault(self.directory, Lock())
        if not lock.acquire(blocking=False):
            raise ValueError("另一个窗口正在保存笔记，请重试")
        stream = None
        acquired = False
        try:
            path = self.directory / ".write.lock"
            if path.exists() or path.is_symlink():
                _regular(path)
            stream = path.open("a+b")
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                raise ValueError("笔记正在被另一个进程保存") from exc
            yield
        finally:
            if stream is not None:
                if acquired:
                    stream.seek(0)
                    if sys.platform == "win32":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
            lock.release()

    def _publish(self, value: dict[str, Any], *, temporary_credit: int = 0) -> None:
        raw = canonical(value)
        if len(raw) > _MAX_FILE:
            raise ValueError("笔记 UTF-8 文件超过保存上限，未截断")
        groups, _ = self._scan()
        if sum(map(len, groups.values())) >= 10000 or (
            value["note_id"] not in groups and len(groups) >= 200
        ):
            raise ValueError("笔记或修订数量已达保存上限")
        total = sum(path.stat().st_size for path in self.directory.iterdir())
        if total + len(raw) - temporary_credit > 64 * 1024 * 1024:
            raise ValueError("笔记修订总量已达保存上限")
        name = f"{value['note_id']}.{value['revision']:08d}"
        final = self.directory / f"{name}.json"
        temporary = self.directory / f".{name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._payload(temporary, value["note_id"], value["revision"])
            if os.name == "nt":
                os.rename(temporary, final)
            else:
                os.link(temporary, final)
                temporary.unlink()
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            # Only this operation's nonce is owned by this writer.
            temporary.unlink(missing_ok=True)

    def create(self, title: str, content: str, *, kind: str = "OTHER") -> AuthorNote:
        validate_note_text(title, title=True)
        validate_note_text(content)
        if kind not in NOTE_KINDS:
            raise ValueError("笔记类型无效")
        with self._write_lock():
            groups, temps = self._scan()
            if temps:
                raise NoteRecoveryRequired("发现未完成的笔记保存，请先恢复或归档暂存文件")
            if len(groups) >= 200:
                raise ValueError("笔记数量已达200篇")
            identity = str(uuid4())
            value = self._new(identity, 1, title, content, kind, None)
            self._publish(value)
            return self._note(value)

    def recoveries(self) -> list[dict[str, Any]]:
        _, temps = self._scan()
        result = []
        for name in sorted(temps):
            match = _TEMP.fullmatch(name)
            assert match is not None
            item: dict[str, Any] = {
                "name": name,
                "note_id": match[1],
                "revision": int(match[2]),
                "valid": False,
                "title": "未完成的笔记保存",
                "content": "",
            }
            try:
                value, _ = self._payload(self.directory / name, match[1], int(match[2]))
                item.update(valid=True, title=value["title"], content=value["content"])
            except ValueError:
                pass
            result.append(item)
        return result

    def recover(self, name: str, *, restore: bool) -> AuthorNote | None:
        match = _TEMP.fullmatch(name) if isinstance(name, str) else None
        if match is None or type(restore) is not bool:
            raise ValueError("暂存文件句柄无效")
        with self._write_lock():
            groups, temps = self._scan()
            if name not in temps:
                raise ValueError("暂存文件已变化，请刷新")
            source = self.directory / name
            result = None
            if restore:
                value, raw = self._payload(source, match[1], int(match[2]))
                chain = groups.get(match[1], [])
                revision = int(match[2])
                if revision <= len(chain):
                    if chain[revision - 1][1] != raw:
                        raise ValueError("暂存内容与已保存修订冲突，请先归档后检查")
                else:
                    previous = hashlib.sha256(chain[-1][1]).hexdigest() if chain else None
                    if revision != len(chain) + 1 or value["previous_revision_hash"] != previous:
                        raise ValueError("暂存文件不是紧邻修订，未自动合并")
                    self._publish(value, temporary_credit=len(raw))
                result = self._note(value)
            archive = self.root / "notes-recovery"
            archive.mkdir(exist_ok=True)
            _regular(archive, directory=True)
            destination = archive / name.lstrip(".")
            if not destination.resolve().is_relative_to(self.root):
                raise ValueError("笔记恢复路径越界")
            if destination.exists():
                _regular(destination)
                if destination.read_bytes() != source.read_bytes():
                    raise ValueError("恢复归档已存在，未覆盖")
                source.unlink()
            elif os.name == "nt":
                os.rename(source, destination)
            else:
                os.link(source, destination)
                source.unlink()
            return result

    def _new(
        self,
        identity: str,
        revision: int,
        title: str,
        content: str,
        kind: str,
        previous: bytes | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "note_id": identity,
            "revision": revision,
            "title": title,
            "kind": kind,
            "content": content,
            "source_hash": note_hash(content),
            "previous_revision_hash": hashlib.sha256(previous).hexdigest() if previous else None,
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
        }

    def save(
        self,
        identity: str,
        content: str,
        *,
        expected_revision: int,
        title: str | None = None,
        kind: str | None = None,
    ) -> AuthorNote:
        note_id(identity)
        validate_note_text(content)
        with self._write_lock():
            groups, temps = self._scan()
            if temps:
                raise NoteRecoveryRequired("发现未完成的笔记保存，请先恢复或归档暂存文件")
            if (
                identity not in groups
                or type(expected_revision) is not int
                or len(groups[identity]) != expected_revision
            ):
                raise ValueError("笔记已有新修订，请重新载入；本地编辑保留")
            previous, raw = groups[identity][-1]
            title = previous["title"] if title is None else title
            kind = previous["kind"] if kind is None else kind
            validate_note_text(title, title=True)
            if kind not in NOTE_KINDS or expected_revision >= 2000:
                raise ValueError("笔记类型或修订上限无效")
            if (title, content, kind) == (previous["title"], previous["content"], previous["kind"]):
                return self._note(previous)
            value = self._new(identity, expected_revision + 1, title, content, kind, raw)
            self._publish(value)
            return self._note(value)
