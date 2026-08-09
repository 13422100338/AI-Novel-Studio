from __future__ import annotations

from ai_novel_studio.core.context.history_retriever import (
    EmbeddingUnavailableError,
)
from ai_novel_studio.domain.embedding import (
    CURRENT_EMBEDDING_SCHEMA_VERSION,
    EmbeddingIndexIdentity,
)
from ai_novel_studio.infrastructure.llm.gateway import (
    LLMGateway,
    MissingCredentialError,
    MissingProviderAdapterError,
)
from ai_novel_studio.infrastructure.llm.provider_adapter import (
    ProviderProtocolError,
    ProviderRequestError,
)
from ai_novel_studio.infrastructure.llm.provider_profile import (
    MissingModelRouteError,
)
from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose

_EMBEDDING_UNAVAILABLE_ERRORS = (
    MissingModelRouteError,
    MissingCredentialError,
    MissingProviderAdapterError,
    ProviderRequestError,
    ProviderProtocolError,
)
_EMBEDDING_IDENTITY_ERRORS = (*_EMBEDDING_UNAVAILABLE_ERRORS, ValueError)


class GatewayEmbeddingProvider:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    @property
    def identity(self) -> EmbeddingIndexIdentity:
        try:
            route = self.gateway.configuration.routes.resolve(
                TaskPurpose.MEMORY_EMBEDDING
            )
            return EmbeddingIndexIdentity(
                route.provider_id,
                route.model_id,
                CURRENT_EMBEDDING_SCHEMA_VERSION,
            )
        except _EMBEDDING_IDENTITY_ERRORS as error:
            raise EmbeddingUnavailableError("Embedding 暂不可用") from error

    @property
    def model_id(self) -> str:
        return self.identity.model_id

    def embed_documents(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        try:
            return self.gateway.embed(TaskPurpose.MEMORY_EMBEDDING, texts)
        except _EMBEDDING_UNAVAILABLE_ERRORS as error:
            raise EmbeddingUnavailableError("Embedding 暂不可用") from error

    def embed_query(self, query: str) -> tuple[float, ...]:
        return self.embed_documents((query,))[0]
