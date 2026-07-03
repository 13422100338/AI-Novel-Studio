from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ai_novel_studio.infrastructure.llm import (
    CapabilityProbe,
    CredentialStore,
    CredentialStoreError,
    LLMGateway,
    ModelCatalog,
    ModelConfigRepository,
    ModelConfiguration,
    ProviderAdapter,
    ProviderError,
    ProviderProfile,
)


class _SettingsJob(QRunnable):
    def __init__(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[BaseException], None],
    ) -> None:
        super().__init__()
        self.function = function
        self.success = success
        self.failure = failure

    @Slot()
    def run(self) -> None:
        try:
            self.success(self.function())
        except BaseException as error:
            self.failure(error)


class ModelSettingsController(QObject):
    models_loaded = Signal(str, object)
    capabilities_loaded = Signal(str, str, object)
    saved = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        repository: ModelConfigRepository,
        credentials: CredentialStore,
        adapters: Mapping[str, ProviderAdapter],
        gateway: LLMGateway | None,
        parent: QObject | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.credentials = credentials
        self.adapters = dict(adapters)
        self.gateway = gateway
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self.configuration = repository.load()

    def has_credential(self, credential_id: str) -> bool:
        try:
            return self.credentials.get(credential_id) is not None
        except CredentialStoreError:
            self.failed.emit("无法读取系统凭据，请检查 Windows 凭据管理器")
            return False

    def refresh_models(self, profile: ProviderProfile, api_key: str) -> None:
        adapter = self.adapters.get(profile.interface_type)
        if adapter is None:
            self.failed.emit(f"没有可用的接口适配器：{profile.interface_type}")
            return
        key = api_key or self.credentials.get(profile.credential_id)
        if not key:
            self.failed.emit("请先输入或保存 API Key")
            return
        self.thread_pool.start(
            _SettingsJob(
                lambda: ModelCatalog().refresh(adapter, profile, key),
                lambda value: self.models_loaded.emit(
                    profile.id, tuple(value) if isinstance(value, tuple) else ()
                ),
                self._emit_failure,
            )
        )

    def save(
        self,
        configuration: ModelConfiguration,
        api_keys: Mapping[str, str],
    ) -> None:
        try:
            self.repository.save(configuration, api_keys)
            self.configuration = configuration
            if self.gateway is not None:
                self.gateway.configuration = configuration
            self.saved.emit(configuration)
        except CredentialStoreError:
            self.failed.emit("无法保存系统凭据，请检查 Windows 凭据管理器")
        except (ValueError, OSError) as error:
            self.failed.emit(str(error))

    def probe_capabilities(
        self,
        profile: ProviderProfile,
        model_id: str,
        api_key: str,
    ) -> None:
        adapter = self.adapters.get(profile.interface_type)
        if adapter is None:
            self.failed.emit(f"没有可用的接口适配器：{profile.interface_type}")
            return
        key = api_key or self.credentials.get(profile.credential_id)
        if not key:
            self.failed.emit("请先输入或保存 API Key")
            return
        self.thread_pool.start(
            _SettingsJob(
                lambda: CapabilityProbe().probe(
                    adapter, profile, key, model_id
                ),
                lambda value: self.capabilities_loaded.emit(
                    profile.id, model_id, value
                ),
                self._emit_failure,
            )
        )

    def _emit_failure(self, error: BaseException) -> None:
        if isinstance(error, ProviderError):
            self.failed.emit(str(error))
        else:
            self.failed.emit("模型列表加载失败，请检查连接地址和网络")
