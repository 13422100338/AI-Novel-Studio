# 前端依赖的后端接口契约（只读摘录）

> 独立前端仓库不包含后端代码。本文摘录前端实际消费的既有应用/存储接口签名，
> 供阅读者理解接线点。实现细节以主仓库为准；前端从未修改这些接口。

## 1. 项目工作区（F2/F3）

`ai_novel_studio.application.project_workspace_service.ProjectWorkspaceService`

```python
def open_project(root: Path) -> ProjectSummary
def summary() -> ProjectSummary            # id/title/root
def volume_tree() -> tuple[VolumeTreeItem, ...]
    # VolumeTreeItem(id, title, chapters: tuple[ChapterTreeItem, ...])
    # ChapterTreeItem(id, declared_number, title, word_count, revision)
def load_chapter(chapter_id: str) -> ChapterWorkspace
    # ChapterWorkspace(id, title, declared_number, content, revision,
    #                  requirement_content, requirement_revision, requirement_locked)
def save_chapter(
    chapter_id: str, content: str, *,
    expected_revision: int,
    requirement_content: str | None = None,
    expected_requirement_revision: int | None = None,
    requirement_locked: bool = False,
) -> SaveChapterResult   # (chapter_id, revision, requirement_revision)
def close_project() -> None
```

仓库层（测试夹具用）：`ProjectRepository.open(root)`；`ChapterRepository.save_content(...,
expected_revision=...)` 在修订过期时抛 `StaleChapterRevisionError`（`save_chapter` 包装为
`RuntimeError("chapter revision is stale")`，前端据此进入 CONFLICT）。

## 2. 人物 / 记忆 / 审校只读概览（F9/F12/F14/F16）

```python
CharacterStatusService(CharacterMemoryRepository(project)).list_cards_for_chapter(
    chapter_id, *, inclusive=False) -> tuple[CharacterStatusCard, ...]
    # Card: id/name/aliases/profile/motivation/psychology/goal/relationships/recent/
    #       journey(CharacterJourneyEntry...)/location/injury_status

MemoryWorkspaceService(ProjectMemoryWorkspaceGateway(project)).load(chapter_id)
    -> MemoryWorkspaceSnapshot(before_chapter_id, records)
    # Record: id/category/title/content/source_type/source_chapter_id/source_revision/
    #         source_hash/authority/review_status/status/revision/editable/promotable/fields

ProjectAuditService(project).latest_model_findings(chapter_id) -> tuple[AuditFinding, ...]
    # 仅返回与当前正文 hash/修订一致的已完成模型审校 run 的 finding
ProjectAuditService(project).update_finding_status(finding_id, AuditFindingStatus) -> AuditFinding
```

## 3. 草稿生成 / 采用（F4–F8；默认未注入端口）

```python
ProjectGenerationSession(project, gateway, history)
  .select_chapter(chapter_id, revision) -> bool
  .prepare_generation(mode: CreationMode, output_token_limit, target_words,
                      audit_policy: AuditPolicy) -> run_id
  .prose.stream(run_id) -> Iterator[ProseGenerationEvent]   # DRAFT_CHUNK/RUN_CHANGED/FAILED
  .accept_current() -> AcceptedGeneration(text, chapter_revision)
  .discard_current() -> bool
  .gateway.usage_tracker.snapshot() -> UsageSnapshot
```

前端 `DraftPort` 协议（`bridge/draft_port.py`）抽象上述接口：
`prepare(chapter_id, revision, GenerationConfig) -> run_id`；
`generate(run_id) -> (text, error)`；`cancel(run_id)`；`usage_snapshot() -> UsageDto`；
`accept_current() -> AcceptedGeneration`；`discard_current() -> bool`。

## 4. WebEngine 桥（Phase 1）

- 下行（Python → JS）：`runJavaScript` 调 `window.__novelEditor.{loadDocument,
  requestSave, undo, redo, findAndReplace, applyTheme, showDecorations, clearDecorations,
  setReadOnly, revealRange, setBaseRevision}`
- 上行（JS → Python）：QWebChannel 单对象 `pythonBridge`：
  `editorReady(protocolVersion, capabilitiesJson)`、`saveRequested(chapterId, baseRevision,
  markdown, contentHash)`、`selectionChanged(from, to)`、`wordCountChanged(count)`
- 校验：协议版本 == 1；能力白名单 `{markdown-v1, selection-v1, decorations-v1}`；
  保存 payload ≤ 5MB；哈希接受 `fnv1a:` 指纹（Phase 1 原型）或真实 SHA-256

### 4.1 选区引用协议（C1）

- JS → Python：`pythonBridge.selectionReferenceChanged(payloadJson)`，
  payload 含 `chapterId / baseRevision / from / to / selectedText /
  selectedTextHash`；空串表示清空（空选区/切章）；
- Python 校验：章节 ID 非空、修订号非负、`from <= to`、位置非负、
  文本非空且 ≤ 20_000 字符、哈希为 `fnv1a:`（8 hex）或 64 hex；
- Facade：`hasSelectionReference`、`selectionReferenceLabel`、
  `selectionReferencePreview`、`clearSelectionReference()`；切章自动清空；
- 下行替换协议（`applyConfirmedReplacement`）属 C4，本轮未实现。

### 4.2 Agent 时间线（C1）

- `AgentTimelineItemDto(kind, text, label, busy, status, options,
  current_text, draft_text, data)`，kind ∈ {user_text, assistant_text,
  run_status, tool_call, tool_result, choice_card, text_diff, confirmation,
  warning, error}；
- `Facade.startAgentTurn(text)` / `stopAgentTurn()` / `agentReplyChoice(i)` /
  `approveAgentChangeSet()` / `discardAgentChangeSet()`；
- 真实后端按文档第 8 节演进为 `CreativeAgentPort`（C2+）。

## 5. 当前未接线点（前端已留 UI/占位）

- `sendDiscussion(text)`：剧情商讨为确定性 Mock 回复；后端应接
  `ModelTaskService.stream_chat`（`TaskPurpose.PLOT_DISCUSSION`）
- 生成端口注入：默认运行时 `draft_port=None`，UI 提示「模型生成端口未配置」
- WebEngine 段落级采用：diff 基线需改为编辑器真相源后接线
