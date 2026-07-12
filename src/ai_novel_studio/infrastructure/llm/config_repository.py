from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from ai_novel_studio.infrastructure.llm.credential_store import CredentialStore
from ai_novel_studio.infrastructure.llm.provider_profile import ProviderProfile, TaskRoutes
from ai_novel_studio.infrastructure.llm.schemas import (
    ModelCapabilities,
    ModelProfile,
    ModelRoute,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text


class ModelConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    providers: tuple[ProviderProfile, ...]
    models: tuple[ModelProfile, ...]
    routes: TaskRoutes

    def __post_init__(self) -> None:
        provider_ids = {provider.id for provider in self.providers}
        if len(provider_ids) != len(self.providers):
            raise ValueError("模型连接 ID 不能重复")
        model_keys = {(model.provider_id, model.model_id) for model in self.models}
        if len(model_keys) != len(self.models):
            raise ValueError("同一连接中的模型 ID 不能重复")
        if any(model.provider_id not in provider_ids for model in self.models):
            raise ValueError("模型引用了不存在的连接")
        routes = [self.routes.plot, self.routes.prose]
        routes.extend(route for _, route in self.routes.overrides)
        if any(
            route is not None and (route.provider_id, route.model_id) not in model_keys
            for route in routes
        ):
            raise ValueError("任务路由引用了不存在的模型")

    @classmethod
    def empty(cls) -> ModelConfiguration:
        return cls(providers=(), models=(), routes=TaskRoutes(plot=None, prose=None))

    def provider(self, provider_id: str) -> ProviderProfile:
        for profile in self.providers:
            if profile.id == provider_id:
                return profile
        raise LookupError(f"未找到模型连接：{provider_id}")

    def model(self, route: ModelRoute) -> ModelProfile:
        for profile in self.models:
            if profile.provider_id == route.provider_id and profile.model_id == route.model_id:
                return profile
        raise LookupError(f"未找到模型：{route.model_id}")


class ModelConfigRepository:
    def __init__(self, path: Path, credentials: CredentialStore) -> None:
        self.path = path
        self.credentials = credentials

    def load(self) -> ModelConfiguration:
        if not self.path.exists():
            return ModelConfiguration.empty()
        try:
            payload = cast(dict[str, object], json.loads(self.path.read_text(encoding="utf-8")))
            if payload.get("schema_version") != 1:
                raise ModelConfigError("不支持的模型配置版本")
            providers = tuple(self._provider(item) for item in self._list(payload, "providers"))
            models = tuple(self._model(item) for item in self._list(payload, "models"))
            routes = self._routes(self._dict(payload, "routes"))
            return ModelConfiguration(providers=providers, models=models, routes=routes)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, ModelConfigError):
                raise
            raise ModelConfigError("模型配置文件格式无效") from error

    def save(
        self,
        configuration: ModelConfiguration,
        api_keys: Mapping[str, str],
    ) -> None:
        previous = self.load() if self.path.exists() else ModelConfiguration.empty()
        current_credentials = {profile.credential_id for profile in configuration.providers}
        for profile in previous.providers:
            if profile.credential_id not in current_credentials:
                self.credentials.delete(profile.credential_id)
        for credential_id, secret in api_keys.items():
            if credential_id not in current_credentials:
                raise ValueError("不能保存未被连接引用的凭据")
            if secret:
                self.credentials.set(credential_id, secret)

        payload = {
            "schema_version": 1,
            "providers": [asdict(provider) for provider in configuration.providers],
            "models": [asdict(model) for model in configuration.models],
            "routes": self._routes_payload(configuration.routes),
        }
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    @staticmethod
    def _routes_payload(routes: TaskRoutes) -> dict[str, object]:
        def route_payload(route: ModelRoute | None) -> dict[str, str] | None:
            return asdict(route) if route is not None else None

        return {
            "plot": route_payload(routes.plot),
            "prose": route_payload(routes.prose),
            "overrides": [
                {"purpose": purpose.value, "route": asdict(route)}
                for purpose, route in routes.overrides
            ],
        }

    @classmethod
    def _provider(cls, value: object) -> ProviderProfile:
        data = cls._mapping(value)
        return ProviderProfile(
            id=cls._string(data, "id"),
            name=cls._string(data, "name"),
            base_url=cls._string(data, "base_url"),
            credential_id=cls._string(data, "credential_id"),
            interface_type=cls._string(data, "interface_type"),
            timeout_seconds=cls._integer(data, "timeout_seconds"),
            models_url=cls._optional_string(data.get("models_url")),
        )

    @classmethod
    def _model(cls, value: object) -> ModelProfile:
        data = cls._mapping(value)
        capability_data = cls._mapping(data.get("capabilities"))
        capabilities = ModelCapabilities(
            context_window=cls._optional_integer(capability_data.get("context_window")),
            max_output_tokens=cls._optional_integer(
                capability_data.get("max_output_tokens")
            ),
            streaming=cls._optional_boolean(capability_data.get("streaming")),
            reasoning=cls._optional_boolean(capability_data.get("reasoning")),
            tools=cls._optional_boolean(capability_data.get("tools")),
            strict_json=cls._optional_boolean(capability_data.get("strict_json")),
            prompt_cache=cls._optional_boolean(capability_data.get("prompt_cache")),
            input_price_per_million=cls._optional_number(
                capability_data.get("input_price_per_million")
            ),
            output_price_per_million=cls._optional_number(
                capability_data.get("output_price_per_million")
            ),
        )
        return ModelProfile(
            provider_id=cls._string(data, "provider_id"),
            model_id=cls._string(data, "model_id"),
            display_name=cls._string(data, "display_name"),
            capabilities=capabilities,
        )

    @classmethod
    def _routes(cls, data: dict[str, object]) -> TaskRoutes:
        overrides: list[tuple[TaskPurpose, ModelRoute]] = []
        for item in cls._list(data, "overrides"):
            entry = cls._mapping(item)
            overrides.append(
                (
                    TaskPurpose(cls._string(entry, "purpose")),
                    cls._route(cls._mapping(entry.get("route"))),
                )
            )
        return TaskRoutes(
            plot=cls._optional_route(data.get("plot")),
            prose=cls._optional_route(data.get("prose")),
            overrides=tuple(overrides),
        )

    @classmethod
    def _optional_route(cls, value: object) -> ModelRoute | None:
        if value is None:
            return None
        return cls._route(cls._mapping(value))

    @classmethod
    def _route(cls, data: dict[str, object]) -> ModelRoute:
        return ModelRoute(
            provider_id=cls._string(data, "provider_id"),
            model_id=cls._string(data, "model_id"),
        )

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ModelConfigError("模型配置字段必须是对象")
        return cast(dict[str, object], value)

    @classmethod
    def _dict(cls, data: dict[str, object], key: str) -> dict[str, object]:
        return cls._mapping(data[key])

    @staticmethod
    def _list(data: dict[str, object], key: str) -> list[object]:
        value = data[key]
        if not isinstance(value, list):
            raise ModelConfigError(f"模型配置字段 {key} 必须是数组")
        return cast(list[object], value)

    @staticmethod
    def _string(data: dict[str, object], key: str) -> str:
        value = data[key]
        if not isinstance(value, str):
            raise ModelConfigError(f"模型配置字段 {key} 必须是文本")
        return value

    @staticmethod
    def _integer(data: dict[str, object], key: str) -> int:
        value = data[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ModelConfigError(f"模型配置字段 {key} 必须是整数")
        return value

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None or isinstance(value, str):
            return value
        raise ModelConfigError("模型配置可选文本字段格式无效")

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ModelConfigError("模型配置可选整数字段格式无效")

    @staticmethod
    def _optional_boolean(value: object) -> bool | None:
        if value is None or isinstance(value, bool):
            return value
        raise ModelConfigError("模型配置可选布尔字段格式无效")

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ModelConfigError("模型配置可选价格字段格式无效")

