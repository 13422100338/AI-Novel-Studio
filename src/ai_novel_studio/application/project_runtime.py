from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_novel_studio.application.agent_loop_service import AgentLoopService
from ai_novel_studio.application.agent_task_service import AgentTaskService
from ai_novel_studio.application.agent_tool_providers import build_project_agent_registry
from ai_novel_studio.application.embedding_index_service import (
    EmbeddingIndexReport,
    EmbeddingIndexService,
)
from ai_novel_studio.application.gateway_embedding_provider import (
    GatewayEmbeddingProvider,
)
from ai_novel_studio.application.project_audit_service import ProjectAuditService
from ai_novel_studio.application.project_brief_service import ProjectBriefService
from ai_novel_studio.application.project_generation_session import (
    ProjectGenerationSession,
)
from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.core.context.history_retriever import (
    HistoryRetriever,
    StoredEmbeddingRecallProvider,
)
from ai_novel_studio.infrastructure.llm import LLMGateway, LLMMessage, TaskPurpose
from ai_novel_studio.infrastructure.storage.agent_repository import AgentRepository
from ai_novel_studio.infrastructure.storage.chat_history_repository import ChatHistoryRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


class HasGateway(Protocol):
    gateway: LLMGateway


class GatewayAgentModelPort:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def complete_json(
        self,
        messages: tuple[LLMMessage, ...],
        *,
        output_token_limit: int,
    ) -> dict[str, object]:
        response = self.gateway.complete(
            TaskPurpose.AGENT_ASSISTANT,
            messages,
            output_token_limit,
            temperature=0.2,
            json_mode=True,
        )
        text = getattr(response, "text", "")
        value = json.loads(str(text))
        if not isinstance(value, dict):
            raise ValueError("agent response must be a JSON object")
        return value


@dataclass(slots=True)
class ProjectRuntime:
    project: ProjectRepository
    workspace: ProjectWorkspaceService
    agent_repository: AgentRepository
    agent_runtime: AgentTaskService
    generation_session: ProjectGenerationSession
    brief_service: ProjectBriefService
    audit_service: ProjectAuditService
    chat_repository: ChatHistoryRepository
    embedding_index: EmbeddingIndexService

    @classmethod
    def create(
        cls,
        root: Path,
        title: str,
        model_runtime: HasGateway,
    ) -> ProjectRuntime:
        workspace = ProjectWorkspaceService()
        workspace.create_project(root, title)
        return cls._from_workspace(workspace, model_runtime)

    @classmethod
    def open(cls, root: Path, model_runtime: HasGateway) -> ProjectRuntime:
        workspace = ProjectWorkspaceService()
        workspace.open_project(root)
        return cls._from_workspace(workspace, model_runtime)

    @classmethod
    def _from_workspace(
        cls,
        workspace: ProjectWorkspaceService,
        model_runtime: HasGateway,
    ) -> ProjectRuntime:
        project = workspace.project
        if project is None:
            raise RuntimeError("project workspace did not open a project")
        agent_repository = AgentRepository(project)
        search = SearchRepository(project)
        embedding_provider = GatewayEmbeddingProvider(model_runtime.gateway)
        history = HistoryRetriever(
            search,
            StoredEmbeddingRecallProvider(search, embedding_provider),
        )
        agent_loop = AgentLoopService(
            agent_repository,
            build_project_agent_registry(project),
            GatewayAgentModelPort(model_runtime.gateway),
        )
        return cls(
            project=project,
            workspace=workspace,
            agent_repository=agent_repository,
            agent_runtime=AgentTaskService(agent_loop),
            generation_session=ProjectGenerationSession(
                project,
                model_runtime.gateway,
                history,
            ),
            brief_service=ProjectBriefService(project, history),
            audit_service=ProjectAuditService(project),
            chat_repository=ChatHistoryRepository(project),
            embedding_index=EmbeddingIndexService(search, embedding_provider),
        )

    def rebuild_pending_embeddings(
        self,
        *,
        limit: int = 100,
        batch_size: int = 16,
    ) -> EmbeddingIndexReport:
        return self.embedding_index.rebuild_pending(
            limit=limit,
            batch_size=batch_size,
        )

    def close(self) -> None:
        self.workspace.close_project()
