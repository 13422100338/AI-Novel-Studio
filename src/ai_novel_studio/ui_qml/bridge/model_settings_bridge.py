"""QML bridge around the neutral model configuration service (RC-2/RC-2f).

Reactive contract: every state QML reads is a notify-backed Property;
mutations update backing fields then emit the exact notify signal.

Thread contract: only service calls run on the QThreadPool. Results are
marshalled back onto the bridge's own thread through a queued Qt signal.
Each completion carries immutable metadata (kind, provider_id, request_id)
so overlapping jobs for different providers cannot cross-contaminate; only
the latest request for the currently-selected provider is applied.

Secrets: API keys travel method-argument -> service and never come back.
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import (
    Property,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    Signal,
    Slot,
)

from ai_novel_studio.application.model_configuration_service import (
    ConfigurationSnapshot,
    ModelConfigurationService,
    ModelConfigurationServiceError,
    ProviderSpec,
)


class _ServiceJob(QRunnable):
    """Runs one blocking service call; results go through a queued signal.

    Each job carries immutable metadata (kind, provider_id, request_id,
    model_id) so the completion dispatcher never has to guess which
    operation or provider a result belongs to — even when jobs overlap.
    """

    def __init__(
        self,
        bridge: QObject,
        function: Any,
        *,
        kind: str,
        provider_id: str,
        request_id: int,
        model_id: str = "",
    ) -> None:
        super().__init__()
        import weakref

        self._bridge_ref = weakref.ref(bridge)
        self._function = function
        self._kind = kind
        self._provider_id = provider_id
        self._request_id = request_id
        self._model_id = model_id

    def run(self) -> None:
        bridge = self._bridge_ref()
        try:
            result = self._function()
            error = ""
        except ModelConfigurationServiceError as exc:
            result, error = None, str(exc)
        except Exception:  # noqa: BLE001 - fixed copy, never raw payloads
            result, error = None, "操作失败，请检查连接设置"
        if bridge is not None:
            # Emitted from this pooled thread; Qt delivers it as a queued
            # call on the thread that owns the bridge (the UI thread).
            bridge._jobFinished.emit(  # type: ignore[attr-defined]
                self._kind, self._provider_id, self._request_id,
                self._model_id, result, error,
            )


class ModelSettingsBridge(QObject):
    providersChanged = Signal()
    currentProviderChanged = Signal()
    availableModelsChanged = Signal()
    routeStateChanged = Signal()
    statusMessageChanged = Signal()
    modelStatusChanged = Signal()
    apiKeyFieldsCleared = Signal()

    # (kind, provider_id, request_id, model_id, result, error)
    _jobFinished = Signal(str, str, int, str, object, str)

    def __init__(
        self,
        service: ModelConfigurationService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._snapshot: ConfigurationSnapshot = service.load_snapshot()
        self._current_provider_id = (
            self._snapshot.providers[0].id if self._snapshot.providers else ""
        )
        first = self._snapshot.providers[0] if self._snapshot.providers else None
        self._draft_name = first.name if first else ""
        self._draft_base_url = first.base_url if first else ""
        self._draft_models_url = (first.models_url or "") if first else ""
        self._draft_interface_type = (
            first.interface_type if first else "openai_compatible"
        )
        self._draft_timeout = first.timeout_seconds if first else 60
        self._editing_new = first is None
        self._available_models: tuple[str, ...] = ()
        self._status_message = ""
        self._request_counter = 0
        self._latest_fetch_by_provider: dict[str, int] = {}
        self._job_lock = threading.Lock()
        self._jobFinished.connect(self._dispatch_job_result)
        self._sync_available_models()

    def _next_request_id(self) -> int:
        with self._job_lock:
            self._request_counter += 1
            return self._request_counter

    def _models_for_provider(self, provider_id: str) -> tuple[str, ...]:
        return tuple(
            m.model_id
            for m in self._snapshot.models
            if m.provider_id == provider_id
        )

    def _sync_available_models(self) -> None:
        """Derive availableModels from snapshot for current provider."""
        self._available_models = self._models_for_provider(
            self._current_provider_id
        )

    # ------------------------------------------------------------------
    # Reactive properties (QML binds these directly).
    # ------------------------------------------------------------------

    @Property("QVariantList", notify=providersChanged)  # type: ignore[arg-type]
    def providers(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "hasCredential": item.has_credential,
            }
            for item in self._snapshot.providers
        ]

    @Property(str, notify=currentProviderChanged)
    def currentProviderId(self) -> str:
        return self._current_provider_id

    @Property(str, notify=currentProviderChanged)
    def draftName(self) -> str:
        return self._draft_name

    @Property(str, notify=currentProviderChanged)
    def draftBaseUrl(self) -> str:
        return self._draft_base_url

    @Property(str, notify=currentProviderChanged)
    def draftModelsUrl(self) -> str:
        return self._draft_models_url

    @Property(str, notify=currentProviderChanged)
    def draftInterfaceType(self) -> str:
        return self._draft_interface_type

    @Property(int, notify=currentProviderChanged)
    def draftTimeout(self) -> int:
        return self._draft_timeout

    @Property(bool, notify=currentProviderChanged)
    def editingNewProvider(self) -> bool:
        return self._editing_new

    @Property(bool, notify=currentProviderChanged)
    def hasCurrentCredential(self) -> bool:
        item = self._snapshot.provider(self._current_provider_id)
        return item.has_credential if item is not None else False

    @Property("QVariantList", notify=availableModelsChanged)  # type: ignore[arg-type]
    def availableModels(self) -> list[str]:
        return list(self._available_models)

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @Property(bool, notify=routeStateChanged)
    def proseReady(self) -> bool:
        return self._snapshot.prose_ready

    @Property(bool, notify=routeStateChanged)
    def plotReady(self) -> bool:
        return self._snapshot.plot_ready

    @Property(str, notify=routeStateChanged)
    def proseRouteText(self) -> str:
        route = self._snapshot.prose_route
        if route is None:
            return "未配置"
        provider = self._snapshot.provider(route.provider_id)
        return f"{provider.name if provider else '连接不可用'} · {route.model_id}"

    @Property(str, notify=routeStateChanged)
    def plotRouteText(self) -> str:
        route = self._snapshot.plot_route
        if route is None:
            return "未配置"
        provider = self._snapshot.provider(route.provider_id)
        return f"{provider.name if provider else '连接不可用'} · {route.model_id}"

    @Property(str, notify=modelStatusChanged)
    def modelStatusText(self) -> str:
        if self._snapshot.prose_ready:
            return "模型 已配置"
        return "模型 未配置"

    # ------------------------------------------------------------------
    # Mutating slots (each emits exact notify signals).
    # ------------------------------------------------------------------

    @Slot(str)
    def selectProvider(self, provider_id: str) -> None:
        item = self._snapshot.provider(provider_id)
        if item is None:
            return
        self._current_provider_id = item.id
        self._draft_name = item.name
        self._draft_base_url = item.base_url
        self._draft_models_url = item.models_url or ""
        self._draft_interface_type = item.interface_type
        self._draft_timeout = item.timeout_seconds
        self._editing_new = False
        self._sync_available_models()
        self.availableModelsChanged.emit()
        self.currentProviderChanged.emit()

    @Slot()
    def beginNewProvider(self) -> None:
        self._current_provider_id = ""
        self._draft_name = ""
        self._draft_base_url = ""
        self._draft_models_url = ""
        self._draft_interface_type = "openai_compatible"
        self._draft_timeout = 60
        self._editing_new = True
        self._available_models = ()
        self.availableModelsChanged.emit()
        self.currentProviderChanged.emit()

    @Slot(str)
    def setDraftName(self, value: str) -> None:
        self._draft_name = value

    @Slot(str)
    def setDraftBaseUrl(self, value: str) -> None:
        self._draft_base_url = value

    @Slot(str)
    def setDraftModelsUrl(self, value: str) -> None:
        self._draft_models_url = value

    @Slot(str)
    def setDraftInterfaceType(self, value: str) -> None:
        self._draft_interface_type = value

    @Slot(int)
    def setDraftTimeout(self, value: int) -> None:
        self._draft_timeout = int(value)

    @Slot(str)
    def saveCurrent(self, api_key: str) -> None:
        spec = ProviderSpec(
            id=None if self._editing_new else (self._current_provider_id or None),
            name=self._draft_name,
            base_url=self._draft_base_url,
            models_url=self._draft_models_url,
            interface_type=self._draft_interface_type,
            timeout_seconds=self._draft_timeout,
        )
        try:
            self._snapshot = self._service.upsert_provider(
                spec, api_key=(api_key or None)
            )
        except ModelConfigurationServiceError as exc:
            self._set_status(str(exc))
            return
        saved_id = spec.id or (
            self._snapshot.providers[-1].id if self._snapshot.providers else ""
        )
        self._current_provider_id = saved_id
        item = self._snapshot.provider(saved_id)
        if item is not None:
            self._draft_name = item.name
            self._draft_base_url = item.base_url
            self._draft_models_url = item.models_url or ""
            self._draft_interface_type = item.interface_type
            self._draft_timeout = item.timeout_seconds
            self._editing_new = False
        self._sync_available_models()
        self.providersChanged.emit()
        self.currentProviderChanged.emit()
        self.availableModelsChanged.emit()
        self.routeStateChanged.emit()
        self.modelStatusChanged.emit()
        self.apiKeyFieldsCleared.emit()
        self._set_status(
            "已保存连接" + ("（凭据已更新）" if api_key else "（保留原密钥）")
        )

    @Slot()
    def removeCurrent(self) -> None:
        if not self._current_provider_id:
            return
        try:
            self._snapshot = self._service.remove_provider(
                self._current_provider_id
            )
        except ModelConfigurationServiceError as exc:
            self._set_status(str(exc))
            return
        first = self._snapshot.providers[0] if self._snapshot.providers else None
        self._current_provider_id = first.id if first else ""
        if first is not None:
            self._draft_name = first.name
            self._draft_base_url = first.base_url
            self._draft_models_url = first.models_url or ""
            self._draft_interface_type = first.interface_type
            self._draft_timeout = first.timeout_seconds
            self._editing_new = False
        else:
            self.beginNewProvider()
        self._sync_available_models()
        self.providersChanged.emit()
        self.availableModelsChanged.emit()
        self.routeStateChanged.emit()
        self.modelStatusChanged.emit()
        self._set_status("已删除连接")

    @Slot(str)
    def refreshModels(self, api_key: str) -> None:
        provider_id = self._current_provider_id
        if not provider_id:
            self._set_status("请先保存一个连接")
            return
        stored_key = api_key
        request_id = self._next_request_id()
        with self._job_lock:
            self._latest_fetch_by_provider[provider_id] = request_id

        # Worker ONLY fetches; persistence happens in the dispatcher after
        # generation validation (P1: stale write before check).
        def work() -> tuple[str, ...]:
            models = self._service.fetch_models(
                provider_id, api_key=stored_key or None
            )
            return tuple(m.model_id for m in models)

        self._pool.start(_ServiceJob(
            self, work,
            kind="fetch", provider_id=provider_id, request_id=request_id,
        ))

    def _dispatch_job_result(
        self,
        kind: str,
        provider_id: str,
        request_id: int,
        model_id: str,
        result: Any,
        error: str,
    ) -> None:
        assert QThread.currentThread() is self.thread(), (
            "bridge completion must run on the bridge's own thread"
        )
        # Relevance check FIRST: stale or non-current results (including
        # their errors) are silently dropped before any state mutation.
        if kind == "fetch":
            with self._job_lock:
                latest = self._latest_fetch_by_provider.get(provider_id, 0)
            if request_id < latest:
                return
            if provider_id != self._current_provider_id:
                # Still persist to disk for background providers, but never
                # touch visible UI state.
                if not error and result is not None:
                    try:
                        self._service.set_models(
                            provider_id, tuple(result)
                        )
                        self._snapshot = self._service.load_snapshot()
                    except ModelConfigurationServiceError:
                        pass
                return
        elif kind == "probe":
            if provider_id != self._current_provider_id:
                return
        else:
            return

        # From here on: result is relevant to the current provider.
        if error:
            self._set_status(error)
            return

        if kind == "fetch":
            try:
                self._service.set_models(provider_id, tuple(result or ()))
                self._snapshot = self._service.load_snapshot()
            except ModelConfigurationServiceError:
                self._set_status("模型目录保存失败，请重试")
                return
            except (OSError, ValueError):
                self._set_status("模型目录保存失败，请检查磁盘权限")
                return
            self._sync_available_models()
            self.availableModelsChanged.emit()
            self.routeStateChanged.emit()
            self.modelStatusChanged.emit()
            self._set_status(f"已获取 {len(self._available_models)} 个模型")
        elif kind == "probe":
            parts: list[str] = []
            for label, flag in (
                ("对话", result.basic_chat),
                ("流式", result.streaming),
                ("JSON", result.strict_json),
                ("推理", result.reasoning),
                ("工具", result.tools),
            ):
                mark = "✓" if flag else ("✗" if flag is False else "?")
                parts.append(f"{label} {mark}")
            self._set_status(f"{model_id} 能力：{'，'.join(parts)}")

    @Slot(str, str)
    def probeCapabilities(self, model_id: str, api_key: str) -> None:
        provider_id = self._current_provider_id
        normalized = model_id.strip()
        if not provider_id or not normalized:
            self._set_status("请先获取模型并选择要探测的模型")
            return
        request_id = self._next_request_id()

        def work() -> Any:
            return self._service.probe_capabilities(
                provider_id, normalized, api_key=api_key or None
            )

        self._pool.start(_ServiceJob(
            self, work,
            kind="probe", provider_id=provider_id,
            request_id=request_id, model_id=normalized,
        ))

    @Slot(str, str)
    def assignRoute(self, kind: str, model_id: str) -> None:
        provider_id = self._current_provider_id
        normalized = model_id.strip()
        if not provider_id or not normalized:
            self._set_status("请先获取模型并选择要探测的模型")
            return

        def as_pair(route: Any) -> tuple[str, str] | None:
            return None if route is None else (route.provider_id, route.model_id)

        if kind == "plot":
            plot: tuple[str, str] | None = (provider_id, normalized)
            prose = as_pair(self._snapshot.prose_route)
        elif kind == "prose":
            plot = as_pair(self._snapshot.plot_route)
            prose = (provider_id, normalized)
        else:
            self._set_status("未知的任务路由")
            return
        try:
            self._snapshot = self._service.set_routes(plot=plot, prose=prose)
        except ModelConfigurationServiceError as exc:
            self._set_status(str(exc))
            return
        self.routeStateChanged.emit()
        self.modelStatusChanged.emit()
        self._set_status("已保存任务路由")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        self._status_message = message
        self.statusMessageChanged.emit()
