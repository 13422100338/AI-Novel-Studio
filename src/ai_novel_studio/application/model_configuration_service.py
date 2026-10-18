"""Framework-neutral model configuration service (QP-2A).

Both the QWidget settings dialog and the QML settings page drive this one
service. It owns the security boundary around model configuration:

- snapshots expose ``has_credential: bool`` per provider and never carry
  secret material;
- API keys are write-only: an empty/omitted key never touches the stored
  credential, and removal is an explicit :meth:`clear_credential` action;
- provider/model catalogs and capability probes are untrusted external
  input; every failure maps to a fixed, sanitized
  :class:`ModelConfigurationServiceError` (no keys, no Authorization
  headers, no raw provider payloads, ``__cause__`` cleared).

The service is fully synchronous on purpose: each UI wraps it with its own
background threading (QThreadPool on both sides).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ai_novel_studio.infrastructure.llm import (
    CapabilityProbe,
    CredentialStore,
    CredentialStoreError,
    ModelCatalog,
    ModelConfigRepository,
    ModelConfiguration,
    ProviderAdapter,
    ProviderError,
    ProviderProfile,
)
from ai_novel_studio.infrastructure.llm.schemas import (
    ModelProfile,
    ModelRoute,
)


class ModelConfigurationServiceError(RuntimeError):
    """Fixed, sanitized failure for UI surfaces."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.__cause__ = None


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Connection fields as edited by a user.

    ``id is None`` creates a new connection; otherwise the existing one is
    replaced in place (its probed models are preserved).
    """

    id: str | None
    name: str
    base_url: str
    models_url: str | None
    interface_type: str
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    id: str
    name: str
    base_url: str
    models_url: str | None
    interface_type: str
    timeout_seconds: int
    has_credential: bool


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    providers: tuple[ProviderSnapshot, ...] = ()
    models: tuple[ModelProfile, ...] = ()
    plot_route: ModelRoute | None = None
    prose_route: ModelRoute | None = None

    @property
    def plot_ready(self) -> bool:
        return self.plot_route is not None

    @property
    def prose_ready(self) -> bool:
        return self.prose_route is not None

    def provider(self, provider_id: str) -> ProviderSnapshot | None:
        for item in self.providers:
            if item.id == provider_id:
                return item
        return None

    def as_dict(self) -> dict[str, Any]:
        def route_dict(route: ModelRoute | None) -> dict[str, str] | None:
            if route is None:
                return None
            return {"provider_id": route.provider_id, "model_id": route.model_id}

        return {
            "providers": [
                {
                    "id": item.id,
                    "name": item.name,
                    "base_url": item.base_url,
                    "models_url": item.models_url,
                    "interface_type": item.interface_type,
                    "timeout_seconds": item.timeout_seconds,
                    "has_credential": item.has_credential,
                }
                for item in self.providers
            ],
            "models": [
                {"provider_id": m.provider_id, "model_id": m.model_id}
                for m in self.models
            ],
            "plot_route": route_dict(self.plot_route),
            "prose_route": route_dict(self.prose_route),
        }


_NO_KEY_MESSAGE = "请先输入或保存 API Key"
_FETCH_FAILURE_MESSAGE = "模型目录获取失败，请检查连接地址与密钥"
_PROBE_FAILURE_MESSAGE = "能力探测失败，请检查连接地址与密钥"


class ModelConfigurationService:
    def __init__(
        self,
        *,
        repository: ModelConfigRepository,
        credentials: CredentialStore,
        adapters: Mapping[str, ProviderAdapter] | None = None,
    ) -> None:
        self._repository = repository
        self._credentials = credentials
        self._adapters: dict[str, ProviderAdapter] = dict(adapters or {})
        self._catalog = ModelCatalog()
        self._probe = CapabilityProbe()

    # -- reads ---------------------------------------------------------------

    def load_snapshot(self) -> ConfigurationSnapshot:
        return self._snapshot(self._load())

    # -- connection mutations --------------------------------------------------

    def upsert_provider(
        self,
        spec: ProviderSpec,
        *,
        api_key: str | None = None,
    ) -> ConfigurationSnapshot:
        config = self._load()
        profile = self._build_profile(spec, config)
        providers = tuple(
            profile if item.id == profile.id else item for item in config.providers
        )
        if not any(item.id == profile.id for item in providers):
            providers = (*providers, profile)
        keys: dict[str, str] = {}
        if api_key:
            keys[profile.credential_id] = api_key
        updated = ModelConfiguration(
            providers=providers, models=config.models, routes=config.routes
        )
        try:
            self._repository.save(updated, keys)
        except CredentialStoreError as error:
            raise self._credential_error(error) from None
        except ValueError as error:
            raise ModelConfigurationServiceError(str(error)) from None
        except OSError:
            raise ModelConfigurationServiceError("无法写入模型配置文件") from None
        return self._snapshot(updated)

    def remove_provider(self, provider_id: str) -> ConfigurationSnapshot:
        config = self._load()
        if not any(item.id == provider_id for item in config.providers):
            raise ModelConfigurationServiceError(f"未找到模型连接：{provider_id}")
        providers = tuple(
            item for item in config.providers if item.id != provider_id
        )
        models = tuple(
            item for item in config.models if item.provider_id != provider_id
        )
        model_keys = {(item.provider_id, item.model_id) for item in models}

        def keep(route: ModelRoute | None) -> ModelRoute | None:
            if route is None:
                return None
            return route if (route.provider_id, route.model_id) in model_keys else None

        from ai_novel_studio.infrastructure.llm.provider_profile import TaskRoutes

        updated = ModelConfiguration(
            providers=providers,
            models=models,
            routes=TaskRoutes(
                plot=keep(config.routes.plot),
                prose=keep(config.routes.prose),
                overrides=tuple(
                    (purpose, kept)
                    for purpose, route in config.routes.overrides
                    if (kept := keep(route)) is not None
                ),
            ),
        )
        try:
            self._repository.save(updated, {})
        except (ValueError, OSError):
            raise ModelConfigurationServiceError("无法写入模型配置文件") from None
        return self._snapshot(updated)

    def clear_credential(self, provider_id: str) -> ConfigurationSnapshot:
        config = self._load()
        profile = self._require_profile(config, provider_id)
        try:
            stored = self._credentials.get(profile.credential_id)
        except CredentialStoreError as error:
            raise self._credential_error(error) from None
        if stored is not None:
            try:
                self._credentials.delete(profile.credential_id)
            except CredentialStoreError as error:
                raise self._credential_error(error) from None
        return self._snapshot(config)

    # -- catalog / probes ------------------------------------------------------

    def fetch_models(
        self,
        provider_id: str,
        *,
        api_key: str | None = None,
    ) -> tuple[ModelProfile, ...]:
        config = self._load()
        profile = self._require_profile(config, provider_id)
        key = self._resolve_key(profile.credential_id, api_key)
        adapter = self._adapters.get(profile.interface_type)
        if adapter is None:
            raise ModelConfigurationServiceError(
                f"没有可用的接口适配器：{profile.interface_type}"
            )
        try:
            models = self._catalog.refresh(adapter, profile, key)
        except ProviderError:
            raise ModelConfigurationServiceError(_FETCH_FAILURE_MESSAGE) from None
        except (OSError, ValueError):
            raise ModelConfigurationServiceError(_FETCH_FAILURE_MESSAGE) from None
        return models

    def set_models(
        self,
        provider_id: str,
        model_ids: tuple[str, ...],
    ) -> ConfigurationSnapshot:
        config = self._load()
        self._require_profile(config, provider_id)
        cleaned: list[ModelProfile] = [
            item
            for item in config.models
            if item.provider_id != provider_id
        ]
        seen: set[str] = set()
        for model_id in model_ids:
            normalized = str(model_id).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(
                ModelProfile(provider_id=provider_id, model_id=normalized)
            )
        routes = self._prune_routes(config.routes, provider_id, cleaned)
        updated = ModelConfiguration(
            providers=config.providers, models=tuple(cleaned), routes=routes
        )
        try:
            self._repository.save(updated, {})
        except (ValueError, OSError):
            raise ModelConfigurationServiceError("无法写入模型配置文件") from None
        return self._snapshot(updated)

    def set_routes(
        self,
        *,
        plot: tuple[str, str] | None,
        prose: tuple[str, str] | None,
    ) -> ConfigurationSnapshot:
        config = self._load()
        from ai_novel_studio.infrastructure.llm.provider_profile import TaskRoutes

        def to_route(value: tuple[str, str] | None) -> ModelRoute | None:
            if value is None:
                return None
            route = ModelRoute(provider_id=value[0], model_id=value[1])
            try:
                config.model(route)
            except LookupError:
                raise ModelConfigurationServiceError(
                    "任务路由引用了不存在的模型"
                ) from None
            return route

        updated = ModelConfiguration(
            providers=config.providers,
            models=config.models,
            routes=TaskRoutes(
                plot=to_route(plot),
                prose=to_route(prose),
                # RC-3: overrides belong to other task surfaces; this method
                # only owns the two base routes and must preserve them.
                overrides=config.routes.overrides,
            ),
        )
        try:
            self._repository.save(updated, {})
        except (ValueError, OSError):
            raise ModelConfigurationServiceError("无法写入模型配置文件") from None
        return self._snapshot(updated)

    def probe_capabilities(
        self,
        provider_id: str,
        model_id: str,
        *,
        api_key: str | None = None,
    ) -> Any:
        config = self._load()
        profile = self._require_profile(config, provider_id)
        key = self._resolve_key(profile.credential_id, api_key)
        adapter = self._adapters.get(profile.interface_type)
        if adapter is None:
            raise ModelConfigurationServiceError(
                f"没有可用的接口适配器：{profile.interface_type}"
            )
        try:
            return self._probe.probe(adapter, profile, key, model_id)
        except ProviderError:
            raise ModelConfigurationServiceError(_PROBE_FAILURE_MESSAGE) from None
        except (OSError, ValueError):
            raise ModelConfigurationServiceError(_PROBE_FAILURE_MESSAGE) from None

    # -- internals -------------------------------------------------------------

    def _load(self) -> ModelConfiguration:
        try:
            return self._repository.load()
        except Exception:  # noqa: BLE001 - repository raises fixed-copy errors
            raise ModelConfigurationServiceError(
                "模型配置读取失败，请检查配置文件"
            ) from None

    def _snapshot(self, config: ModelConfiguration) -> ConfigurationSnapshot:
        providers: list[ProviderSnapshot] = []
        for profile in config.providers:
            try:
                has_key = self._credentials.get(profile.credential_id) is not None
            except CredentialStoreError as error:
                raise self._credential_error(error) from None
            providers.append(
                ProviderSnapshot(
                    id=profile.id,
                    name=profile.name,
                    base_url=profile.base_url,
                    models_url=profile.models_url,
                    interface_type=profile.interface_type,
                    timeout_seconds=profile.timeout_seconds,
                    has_credential=has_key,
                )
            )
        return ConfigurationSnapshot(
            providers=tuple(providers),
            models=config.models,
            plot_route=config.routes.plot,
            prose_route=config.routes.prose,
        )

    def _build_profile(
        self,
        spec: ProviderSpec,
        config: ModelConfiguration,
    ) -> ProviderProfile:
        profile_id = spec.id
        if profile_id is None:
            profile_id = uuid.uuid4().hex[:12]
        elif not any(item.id == profile_id for item in config.providers):
            raise ModelConfigurationServiceError(
                f"未找到模型连接:{profile_id}"
            )
        try:
            return ProviderProfile(
                id=profile_id,
                name=spec.name.strip(),
                base_url=spec.base_url.strip(),
                credential_id=f"provider.{profile_id}",
                interface_type=spec.interface_type.strip() or "openai_compatible",
                timeout_seconds=spec.timeout_seconds,
                models_url=(
                    spec.models_url.strip() if spec.models_url else None
                ),
            )
        except ValueError as error:
            raise ModelConfigurationServiceError(str(error)) from None

    def _require_profile(
        self,
        config: ModelConfiguration,
        provider_id: str,
    ) -> ProviderProfile:
        try:
            return config.provider(provider_id)
        except LookupError:
            raise ModelConfigurationServiceError(
                f"未找到模型连接:{provider_id}"
            ) from None

    def _resolve_key(
        self,
        credential_id: str,
        api_key: str | None,
    ) -> str:
        if api_key:
            return api_key
        try:
            stored = self._credentials.get(credential_id)
        except CredentialStoreError as error:
            raise self._credential_error(error) from None
        if not stored:
            raise ModelConfigurationServiceError(_NO_KEY_MESSAGE)
        return stored

    @staticmethod
    def _credential_error(
        _error: CredentialStoreError,
    ) -> ModelConfigurationServiceError:
        return ModelConfigurationServiceError(
            "无法访问系统凭据库，请检查 Windows 凭据管理器"
        )

    @staticmethod
    def _prune_routes(routes: Any, provider_id: str, models: list[ModelProfile]) -> Any:
        from ai_novel_studio.infrastructure.llm.provider_profile import TaskRoutes

        model_keys = {(item.provider_id, item.model_id) for item in models}

        def keep(route: ModelRoute | None) -> ModelRoute | None:
            if route is None:
                return None
            if route.provider_id != provider_id:
                return route
            return route if (route.provider_id, route.model_id) in model_keys else None

        return TaskRoutes(
            plot=keep(routes.plot),
            prose=keep(routes.prose),
            overrides=tuple(
                (purpose, kept)
                for purpose, route in routes.overrides
                if (kept := keep(route)) is not None
            ),
        )
