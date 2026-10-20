"""Immutable, checksummed writer messages; no model keys or mutable source lookups."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

MAX_WRITER_INPUT_BYTES = 64_000_000


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


class WriterInputRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def _path(self, run_id: str) -> Path:
        validate_id(run_id)
        path = self.project.layout.pipeline / "writer_inputs" / f"{run_id}.json"
        if (
            path.resolve()
            != self.project.layout.root / ".ai_pipeline" / "writer_inputs" / f"{run_id}.json"
        ):
            raise ValueError("正文输入快照目录异常，未读写文件")
        return path

    def save(
        self,
        run_id: str,
        manifest_id: str,
        messages: tuple[LLMMessage, ...],
        metadata: dict[str, Any],
    ) -> None:
        validate_id(manifest_id)
        if metadata.get("author_confirmed") is not True or not messages:
            raise ValueError("正文输入未经作者确认")
        payload = {
            "version": 1,
            "project_id": self.project.project.id,
            "run_id": run_id,
            "manifest_id": manifest_id,
            "metadata": metadata,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        body = _canonical(payload)
        envelope = _canonical({"payload": payload, "sha256": hashlib.sha256(body).hexdigest()})
        if len(envelope) > MAX_WRITER_INPUT_BYTES:
            raise ValueError("完整正文输入快照超过 64MB，未截断或启动生成")
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path(run_id)
        with path.open("xb") as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())

    def load(self, run_id: str) -> dict[str, Any]:
        try:
            with self._path(run_id).open("rb") as stream:
                raw = stream.read(MAX_WRITER_INPUT_BYTES + 1)
            if len(raw) > MAX_WRITER_INPUT_BYTES:
                raise ValueError
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
                raise ValueError
            payload = envelope["payload"]
            if not isinstance(payload, dict) or set(payload) != {
                "version",
                "project_id",
                "run_id",
                "manifest_id",
                "metadata",
                "messages",
            }:
                raise ValueError
            if envelope["sha256"] != hashlib.sha256(_canonical(payload)).hexdigest():
                raise ValueError
            run = GenerationRepository(self.project).get(run_id)
            if (
                type(payload["version"]) is not int
                or payload["version"] != 1
                or payload["project_id"] != self.project.project.id
                or payload["run_id"] != run_id
                or payload["manifest_id"] != run.context_manifest_id
                or not isinstance(payload["metadata"], dict)
                or payload["metadata"].get("author_confirmed") is not True
                or payload["metadata"].get("model") != run.model_id
                or payload["metadata"].get("provider_id") != run.model_provider_id
                or payload["metadata"].get("chapter_id") != run.chapter_id
                or not isinstance(payload["messages"], list)
                or not payload["messages"]
            ):
                raise ValueError
            for message in payload["messages"]:
                if (
                    not isinstance(message, dict)
                    or set(message) != {"role", "content"}
                    or message["role"] not in {"system", "user"}
                    or not isinstance(message["content"], str)
                    or not message["content"].strip()
                ):
                    raise ValueError
            return payload
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "正文输入快照缺失或损坏，已停止；不会重新检索或拼接当前资料。"
            ) from exc

    def messages_for(self, run_id: str) -> tuple[LLMMessage, ...]:
        return tuple(LLMMessage(m["role"], m["content"]) for m in self.load(run_id)["messages"])
