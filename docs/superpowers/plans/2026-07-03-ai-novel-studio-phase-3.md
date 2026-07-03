# AI Novel Studio Phase 3 Model Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral, OpenAI-compatible model gateway with safe local configuration, dual-model routing, capability discovery, streaming, output contracts, usage accounting, and Phase 3 UI integration without enabling the Phase 5 prose pipeline early.

**Architecture:** UI widgets emit user intent to an application-layer coordinator. The coordinator invokes task services, which route through `LLMGateway`; only provider adapters perform HTTP. Provider metadata is stored as JSON, API keys are stored separately in Windows Credential Manager, and model output is validated by contracts before reaching UI state. Phase 3 may normalize a Chapter Brief, audit style, converse about plot, and draft Current Chapter Requirement, but it must not mutate project storage or generate/save formal prose.

**Tech Stack:** Python 3.11+, PySide6, standard-library `urllib`, Windows Credential Manager via `ctypes`, pytest, pytest-qt, Ruff, mypy, PyInstaller.

## Global Constraints

- UI must never call provider adapters directly.
- API keys must not enter JSON configuration, logs, Git history, exports, or exception text.
- No silent provider/model fallback; a failed paid call remains failed.
- Structured output receives at most one format-correction retry.
- A partial streamed result is surfaced as partial output and is never silently regenerated.
- Plot discussion and prose routes are independently configurable; prose generation remains disabled until Phase 5.
- Current Chapter Requirement remains editable and lockable; model output cannot overwrite it while locked.
- User-selectable output Token limits remain in the `256..200000` range and are never clamped to 3000.
- Adapters do not write project storage.

---

### Task 1: Provider-neutral schemas and routing

**Files:**
- Create: `src/ai_novel_studio/infrastructure/llm/schemas.py`
- Create: `src/ai_novel_studio/infrastructure/llm/provider_profile.py`
- Modify: `src/ai_novel_studio/infrastructure/llm/__init__.py`
- Test: `tests/unit/llm/test_schemas_and_routing.py`

**Interfaces:**
- Produces `ProviderProfile`, `ModelProfile`, `ModelCapabilities`, `TaskPurpose`, `TaskRoutes`, `LLMMessage`, `LLMRequest`, `LLMResponse`, `LLMUsage`, and `ModelRoute`.
- `TaskRoutes.resolve(purpose) -> ModelRoute` uses explicit advanced overrides before the plot/prose defaults and raises `MissingModelRouteError` instead of guessing.

- [x] **Step 1: Write failing tests** for URL normalization, output-limit validation, advanced-route precedence, and missing-route errors.
- [x] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests\unit\llm\test_schemas_and_routing.py -q` and confirm imports fail because the Phase 3 types do not exist.
- [x] **Step 3: Implement immutable dataclasses and enums.** `ProviderProfile` stores only a `credential_id`, never a key; `LLMRequest` rejects empty messages and limits outside `1..200000`; `TaskRoutes.resolve` is deterministic.
- [x] **Step 4: Run the focused tests and full suite.**
- [x] **Step 5: Commit** `feat: add model profiles and task routing`.

### Task 2: Secret-safe configuration repository

**Files:**
- Create: `src/ai_novel_studio/infrastructure/llm/credential_store.py`
- Create: `src/ai_novel_studio/infrastructure/llm/config_repository.py`
- Test: `tests/unit/llm/test_model_config_repository.py`

**Interfaces:**
- Produces `CredentialStore` protocol, `WindowsCredentialStore`, `MemoryCredentialStore`, `ModelConfiguration`, and `ModelConfigRepository`.
- `ModelConfigRepository.save(configuration, api_keys)` writes profiles/routes atomically and delegates secrets to `CredentialStore`.
- `ModelConfigRepository.load() -> ModelConfiguration` returns an empty valid configuration when no file exists.

- [x] **Step 1: Write failing tests** proving round-trip persistence, atomic JSON shape, absence of API-key text, deletion of retired credentials, and empty-first-run behavior.
- [x] **Step 2: Run focused tests and confirm missing symbols.**
- [x] **Step 3: Implement the repository** using `atomic_write_text`; JSON contains schema version, provider metadata, model metadata, and routes only.
- [x] **Step 4: Implement Windows generic credentials** with `CredWriteW`, `CredReadW`, `CredDeleteW`, and `CredFree`; redact target identifiers in raised errors.
- [x] **Step 5: Run focused tests, privacy scan, and full suite.**
- [x] **Step 6: Commit** `feat: store model configuration without api secrets`.

### Task 3: OpenAI-compatible adapter, model catalog, and capability probe

**Files:**
- Create: `src/ai_novel_studio/infrastructure/llm/provider_adapter.py`
- Create: `src/ai_novel_studio/infrastructure/llm/model_catalog.py`
- Test: `tests/unit/llm/test_openai_compatible_adapter.py`
- Test: `tests/unit/llm/test_model_catalog.py`

**Interfaces:**
- Produces `ProviderAdapter`, `HttpTransport`, `UrllibTransport`, `OpenAICompatibleAdapter`, `ModelCatalog`, and `CapabilityProbe`.
- `OpenAICompatibleAdapter.list_models(profile, api_key) -> tuple[str, ...]` supports `/models` and custom list URLs.
- `complete(request, profile, api_key) -> LLMResponse` parses OpenAI-compatible text, reasoning content, and usage without assuming optional fields.
- `stream(request, profile, api_key) -> Iterator[LLMStreamEvent]` parses SSE data frames and emits text, usage, completion, and partial-failure events.

- [x] **Step 1: Write failing transport-driven tests** for authorization headers, third-party Base URLs, model listing, usage parsing, SSE chunk order, `[DONE]`, and non-secret error messages.
- [x] **Step 2: Run tests and confirm missing adapter behavior.**
- [x] **Step 3: Implement injectable transport and adapter** with standard-library networking, explicit timeouts, and typed provider errors.
- [x] **Step 4: Implement catalog and opt-in capability probes** for basic chat, streaming, JSON, tools, reasoning, and usage fields; unknown remains unknown.
- [x] **Step 5: Run focused tests and full suite.**
- [x] **Step 6: Commit** `feat: add openai compatible provider adapter`.

### Task 4: Gateway, contracts, retry policy, and usage accounting

**Files:**
- Create: `src/ai_novel_studio/infrastructure/llm/retry_policy.py`
- Create: `src/ai_novel_studio/infrastructure/llm/usage_tracker.py`
- Create: `src/ai_novel_studio/infrastructure/llm/gateway.py`
- Create: `src/ai_novel_studio/infrastructure/llm/contract_runner.py`
- Test: `tests/unit/llm/test_gateway_and_contracts.py`
- Test: `tests/unit/llm/test_usage_tracker.py`

**Interfaces:**
- `LLMGateway.complete(purpose, messages, output_token_limit) -> LLMResponse` resolves exactly one configured route and records the call.
- `LLMGateway.stream(...) -> Iterator[LLMStreamEvent]` never retries after content has arrived.
- `LLMContractRunner.run_json(..., contract) -> dict[str, object]` extracts fenced or plain JSON, validates required fields, and performs at most one correction call.
- `UsageTracker.snapshot() -> UsageSnapshot` separates actual values from estimates and reports cache status as known/unknown.

- [x] **Step 1: Write failing tests** for route selection, missing keys, retry before content, no retry after partial content, one contract correction, second failure stop, usage aggregation, cache-unknown display, and price calculation.
- [x] **Step 2: Run focused tests and confirm expected failures.**
- [x] **Step 3: Implement gateway and bounded retry policy.**
- [x] **Step 4: Implement text/JSON contracts and explicit `ContractValidationError`.**
- [x] **Step 5: Implement usage tracking with actual/estimated flags.**
- [x] **Step 6: Run focused tests, full suite, Ruff, and mypy.**
- [x] **Step 7: Commit** `feat: add validated model gateway and usage tracking`.

### Task 5: Phase 3 model task service and background coordinator

**Files:**
- Create: `src/ai_novel_studio/application/model_tasks.py`
- Create: `src/ai_novel_studio/application/model_task_coordinator.py`
- Test: `tests/unit/application/test_model_tasks.py`
- Test: `tests/ui/test_model_task_coordinator.py`

**Interfaces:**
- `ModelTaskService.chat(messages, manuscript_excerpt) -> LLMResponse` uses `PLOT_DISCUSSION`.
- `draft_chapter_requirement(...) -> str` uses a non-empty text contract and never writes UI or storage.
- `normalize_brief(source) -> NormalizedBrief` and `audit_style(text, rules) -> StyleAuditResult` use JSON contracts.
- `ModelTaskCoordinator` exposes Qt signals for chat chunks, requirement result, Brief result, audit result, usage changes, and sanitized failures while executing work outside the GUI thread.

- [x] **Step 1: Write failing tests** that assert task purpose, prompt order, contract fields, no repository dependency, streaming signal order, and sanitized errors.
- [x] **Step 2: Run focused tests and confirm missing services.**
- [x] **Step 3: Implement deterministic prompt builders** with stable system instructions first and dynamic task content last.
- [x] **Step 4: Implement `QRunnable` jobs and coordinator signals** with one in-flight job per UI action.
- [x] **Step 5: Run focused tests and full suite.**
- [x] **Step 6: Commit** `feat: add background model task coordination`.

### Task 6: Settings, dual-model UI, model actions, and metrics

**Files:**
- Modify: `src/ai_novel_studio/ui/pages/settings_dialog.py`
- Modify: `src/ai_novel_studio/ui/panels/plot_chat_panel.py`
- Modify: `src/ai_novel_studio/ui/pages/brief_dialog.py`
- Modify: `src/ai_novel_studio/ui/pages/audit_window.py`
- Modify: `src/ai_novel_studio/ui/panels/top_bar.py`
- Modify: `src/ai_novel_studio/ui/panels/manuscript_panel.py`
- Modify: `src/ai_novel_studio/ui/main_window.py`
- Test: `tests/ui/test_phase_3_model_ui.py`
- Test: `tests/ui/test_accessibility_and_layout.py`

**Interfaces:**
- Settings manages multiple connections, third-party Base URL, hidden API key, timeout, model refresh, capability status, plot/prose route selection, and advanced Brief/audit routes.
- Plot chat sends through the coordinator and renders streamed assistant output; “生成当前章要求” applies only an unlocked result.
- Brief dialog gains explicit “AI 整理草稿”; audit gains “运行模型审校”. Neither action writes project storage.
- Top metrics consume `UsageSnapshot`; actual and estimated data are visually distinguished.

- [x] **Step 1: Write failing UI tests** for editable third-party profiles, password-mode key field, independent route combos, model-list refresh signal, custom `200000` output limit retention, locked requirement protection, bubble streaming, Brief normalization, audit findings, and metric updates.
- [x] **Step 2: Run focused tests and verify expected Phase 2 failures.**
- [x] **Step 3: Implement the settings widgets and controller boundary.**
- [x] **Step 4: Wire MainWindow to the coordinator; keep prose generation disabled with a Phase 5 tooltip and repair disabled with a Phase 6 tooltip.**
- [x] **Step 5: Run focused UI tests and full suite offscreen.**
- [x] **Step 6: Commit** `feat: connect phase 3 model controls to the workspace`.

### Task 7: Documentation, release verification, and Windows build

**Files:**
- Create: `docs/architecture/0004-unified-model-gateway.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-02-director-writer-workflow-design.md`
- Modify: `scripts/verify_release.ps1` only if new Phase 3 artifacts require scanning changes.

**Interfaces:**
- Documents provider boundaries, secret handling, routing precedence, prompt order, contract correction, partial-stream behavior, usage provenance, and Phase 3/5 separation.

- [ ] **Step 1: Document the implemented behavior and operator workflow** without real provider names, keys, private paths, or personal identity.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest -q`, Ruff, mypy, `scripts\verify_release.ps1`, and `scripts\build_windows.ps1`.
- [ ] **Step 3: Verify the built EXE exists and release privacy scan passes on `dist`.**
- [ ] **Step 4: Commit** `docs: document phase 3 model gateway`.
- [ ] **Step 5: Fast-forward merge into `codex/phase-1-data-kernel`, synchronize the clean Desktop repository, compare EXE hashes, and do not push GitHub.**

## Self-review

- Spec coverage: multi-connection, third-party model lists, dual-model and advanced task routes, capability probing, streaming, contracts, bounded retries, usage/cost/cache reporting, and custom chapter output limits are each assigned to a task.
- Phase boundary: prose generation/checkpoints remain Phase 5; deterministic audit/repair remains Phase 6; memory retrieval remains Phase 4.
- Privacy: API keys have a separate credential store and are covered by repository and release tests.
- Type consistency: gateway, coordinator, UI, and tests use the same `TaskPurpose`, `LLMResponse`, `LLMStreamEvent`, and `UsageSnapshot` interfaces.
- Placeholder scan: no task contains a deferred implementation placeholder.
