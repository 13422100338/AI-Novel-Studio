# AI Novel Studio 后端重构补充升级计划

> 日期：2026-08-09
> 审计基线：`main` @ `442ae15`
> 状态：规划已更新，尚未授权实现
> 主题：共享 Occurrence / View 稀疏化 / Subject 历程查询 / Formal Manuscript 历史证据回查

## 1. 文档定位

本文是以下既有后端计划的增量升级，不替代历史交接记录：

- `docs/handoffs/2026-07-22-backend-refactor-handoff.md`
- `docs/handoffs/BACKEND_WORKTREE_BOARD.md`
- `docs/architecture/0011-subject-registry.md`
- `docs/architecture/0012-view-assertions.md`
- `docs/architecture/0020-hybrid-history-recall.md`
- `docs/architecture/0021-memory-embedding-cache-schema.md`

升级依据是两份 2026-08-09 只读审计输入：

- `AI-Novel-Studio-共享事件View稀疏化与Subject历程查询-后端补充约束-v0.1.md`
- `AI-Novel-Studio-正文RAG与历史细节回查-后端补充约束-v0.1.md`

本文只冻结方向、边界、依赖和实施票。任何 schema、公共 DTO、Context Manifest
格式或 Agent Tool 变更，仍需单独的主控授权。

## 2. 不变的最高架构约束

1. Formal Manuscript 仍是正式正文唯一权威源。
2. Backend 仍拥有 Domain Truth；模型输出只能先成为待审候选。
3. Context Compiler 仍是正式生成上下文唯一入口。
4. 现有 `HistoryRetriever`、`SearchRepository`、Embedding cache、Context Builder 和
   Manifest 必须渐进扩展，不得建立第二套 RAG 或第二条 Context 主链。
5. Occurrence 是可重建、可失效的结构化世界事件，不得反向覆盖 Formal Manuscript。
6. Character State Event 仍只表达某个 Subject 的状态变化，不得兼任共享剧情事件。
7. View Assertion 只保存认知差异，不得成为完整世界副本或全量认知矩阵。
8. Subject 历程默认返回紧凑索引，事件详情和正文证据必须按需逐级展开。
9. 向量、FTS、Occurrence projection、Evidence cache 都是派生数据，不是新的真相源。
10. 所有时间、权限、修订、审查、失效和冲突判定最终必须进入统一可审计边界。

## 3. 当前实现审计

### 3.1 已完成

| 能力 | 当前证据 | 结论 |
| --- | --- | --- |
| 稳定人物 Subject 与别名 | `domain/subject.py::SubjectType`、`SubjectRepository` | 已完成 CHARACTER 基线 |
| View 四类与双时间范围 | `domain/view.py::ViewAssertionDraft` | 已完成基础数据合同 |
| View 审查、来源修订和失效 | `ViewAssertionRepository`、`ViewAssertionContextProvider` | 已完成并进入 Context hard filter |
| 模型 View 候选先审后用 | `ViewAssertionExtractionService`、C5-C12 | 已完成 |
| 混合召回四路 | `SearchRepository.search_rows()`：EXACT_PHRASE、KEYWORD、EMBEDDING、SUBJECT | 已完成 |
| 真实 Embedding 生产装配 | `ProjectRuntime._from_workspace()`、`GatewayEmbeddingProvider` | 已完成 A1-A4 |
| 可替换向量缓存 | schema v16、`EmbeddingIndexService` | 已完成 |
| 章节来源 revision/hash | `SearchDocument.source_revision/source_hash` | 已完成文档级来源绑定 |
| 章节修改后的依赖失效 | `ChapterRepository.save_content()`、`MemoryDependencyRepository` | 已完成旧来源失效传播 |
| Writer 上下文统一入口 | `GenerationMemoryContextProvider` → `ContextBuilder` → `ContextManifest` | 已完成 |
| Context Manifest v2 兼容读取 | `core/context/context_manifest.py` | 已完成 M1 |

### 3.2 部分完成

| 约束 | 当前状态 | 缺口 |
| --- | --- | --- |
| Formal Manuscript 检索 | `SearchRepository.index_chapter()` 可把整章写入 FTS/Embedding | 仍是整章文档，不是 revision-aware chunk；没有 offset/range |
| Exact Evidence | FTS `snippet()` 或正文前 240 字可进入 `SearchHit.excerpt` | 不能稳定回到精确正文范围，也没有邻接 chunk hydrate |
| 增量更新 | 章节保存会使 SEARCH dependency 和 embedding 失效 | 不会自动为新 revision 局部重建文档、FTS 和向量 |
| Retrieval provenance | `SearchHit` 有 route 与分项分数，Manifest 有 source revision/hash | route、score、range 没有进入正式 Manifest / Retrieval Trace |
| Agent 历史查询 | 有 `SEARCH_MEMORY`、`READ_CHAPTER_EXCERPT` 和人物状态/知识工具 | 没有统一 `query_subject_history/get_occurrence/query_subject_evidence` |
| Reader/POV View | 有时间、修订、审查与 Context 过滤 | 抽取规则没有硬性要求“只保存认知差异” |
| Reader visibility | `READER_VIEW` 必须有 `narrative_visible_from_sequence` | 普通正文显式事实尚不能直接从 Formal Manuscript 位置派生可见性 |
| Subject recall | Search 文档可保存 participant IDs | 没有共享 Occurrence / Participant Link 语义 |
| 临时证据生命周期 | 检索块只在当前 Context 编译中使用 | 没有显式 EvidenceSet / cache 失效合同 |

### 3.3 尚未实现

当前代码中不存在以下正式领域能力：

- `Occurrence`
- `OccurrenceParticipant` / `SubjectOccurrenceLink`
- `caused_by_occurrence_id`
- `SubjectHistoryItem` / `SubjectHistoryProjection`
- `ReaderVisibility` 派生投影
- `query_subject_history`
- `get_occurrence`
- `query_subject_evidence`
- Formal Manuscript chunk DTO（含 revision、offset、source range）
- `EvidenceSet` / `EvidenceHit`
- Formal Manuscript 专用 retrieval namespace
- 章节提交后的自动局部重索引
- 带 retrieval route/score/range 的 Manifest trace

`NarrativeClueEvent` 是伏笔状态变化，`CharacterStateEvent` 是人物状态变化，
`ProvenanceEvent` 是审计事件；三者都不能被直接重命名为共享 Occurrence。

## 4. 对原计划的修正

### 4.1 原 Phase 3：从“Hybrid Recall”升级为“可回源历史证据”

原 Phase 3 已完成的四路混合召回继续保留，但不能再把“能召回整章”视为正文 RAG
完成。Phase 3 的剩余验收目标升级为：

```text
Formal Manuscript current revision
→ bounded revision-aware chunks
→ lexical + embedding + subject/metadata recall
→ deterministic candidate merge/rerank
→ exact source-range hydration
→ authority/time/view/revision validation
→ temporary EvidenceSet
→ Context Compiler
→ Context Manifest / Retrieval Trace
```

必须同时支持：

- 精确专名、台词和数字的 lexical route；
- 同义表达的 embedding route；
- Subject/alias/metadata 加权；
- 当前有效 revision；
- 未来章节隔离；
- 候选稿、旧 revision 和 stale chunk 排除；
- NOT_FOUND / insufficient evidence，不得根据摘要猜测。

### 4.2 原 Phase 4：拆分为 State Events 与 Shared Occurrence 两条责任

原 Phase 4 的 Character State Event/Snapshot 基线已完成 SE1-SE3，但它只解决
“某个 Subject 发生了什么状态变化”。新增的 Shared Occurrence 子阶段解决
“世界中发生了一件哪些 Subject 共同参与的事件”：

```text
1 Occurrence
+ N Participant Links
+ 少量真实 State Events
+ 少量真实 View Assertions
```

明确禁止：

- 为每个参与者复制完整事件；
- 为普通目击自动生成 CHARACTER_VIEW/KNOWS；
- 建立参与者 × 观察者的 N×N View 矩阵；
- 把完整 Occurrence JSON 复制进每个 Subject；
- 把 Occurrence 当作 Formal Manuscript。

### 4.3 原 Phase 2：增加 View 稀疏化收口

现有 View Assertion 存储、审查和 Context 过滤保留。后续只收紧创建策略：

- 普通正文显式事实不生成重复 READER_VIEW；
- 普通参与/目击不生成 CHARACTER_VIEW；
- Reader visibility 优先由 Formal Manuscript 的 narrative position 派生；
- 显式 View 仅保存秘密、误导、怀疑、部分揭露、隐藏和错误信念等高价值差异；
- AUTHOR_PLAN/PLANNED_OCCURRENCE 不得自动变成 Reader 已知；
- 后文揭晓不得污染前文查询。

### 4.4 Agent Harness：增加 Progressive Retrieval，而不是原始数据库工具

Agent 只看到四个高层能力：

```text
query_subject_history
get_occurrence
query_subject_state
query_subject_evidence
```

不得暴露 `bm25_search/vector_search/load_chunk/get_all_events_raw` 等低层编排工具。

Subject 历程采用三级展开：

1. `INDEX`：sequence、类型、`occurrence_id`、role、短 `subject_summary`、关联 state IDs；
2. `STRUCTURED_DETAIL`：一个 Occurrence 的参与者、动作、结果与关联 State Events；
3. `EVIDENCE`：沿 source refs 回查当前有效 Formal Manuscript 原文。

默认只返回 Level 1。Level 2/3 必须由明确任务需要触发，并受结果条数、字符数和
Context token budget 限制。

## 5. 冻结的数据职责

### 5.1 Occurrence

Occurrence 只保存共享事件本体的结构化摘要与来源身份，建议最小合同：

```text
id
type
title
summary
narrative_sequence
authority
canonical_status
source_refs
source_revision/hash
status
created_by
created_at/updated_at
```

字段名以实施前只读审计为准；不得在未审计现有近义结构前直接建表。

### 5.2 SubjectOccurrenceLink

Link 只保存：

```text
subject_id
occurrence_id
role
subject_summary
importance
source_refs
linked_state_event_ids
```

`subject_summary` 是人物中心的短投影，不是完整事件副本。

### 5.3 State Event

只有长期状态真的改变时才产生。未来可以引用 `caused_by_occurrence_id`，但不能要求
每个 Participant 都生成 State Event。

### 5.4 View Assertion

View 只描述观察者与目标事实之间的认知差异。它可以指向 Occurrence、Subject、
Fact、Relationship 或 Secret，但不复制 Occurrence 的参与者、动作与结果。

### 5.5 Formal Manuscript Evidence

正文 Evidence 必须至少携带：

```text
chapter_id
chapter_order
revision
source_hash
start_offset
end_offset
source_type = FORMAL_MANUSCRIPT
canonical/current status
retrieval_routes
diagnostic scores
```

检索分数只用于诊断和排序，不是事实真值。

## 6. 分阶段实施票

每张票都必须从最新 `main` 创建独立 worktree，先 RED 后 GREEN；一次只授权一张。

### Gate S0：语义与现有结构只读审计

目标：

- 对 story/event/occurrence/participant/subject history 近义结构做 REUSE/ADAPT/MISSING/CONFLICT 映射；
- 对 `memory_documents`、FTS、embedding、revision dependency、Context Manifest 和
  Agent tools 做相同映射；
- 冻结 Occurrence、Participant Link、EvidenceHit 和 Progressive History 公共合同；
- 形成两个 Proposed ADR：共享 Occurrence；Formal Manuscript Evidence Retrieval。

本 Gate 不修改 schema 或生产代码。

### Ticket R1：Formal Manuscript chunk 派生索引

目标：

- 在现有 Search/Embedding 边界内增加 revision-aware chunk；
- 每个 chunk 可定位到 chapter/revision/start/end/hash；
- 明确 `FORMAL_MANUSCRIPT` namespace；
- 保留 FTS lexical 与现有 Embedding cache；
- chunk 和向量都可重建，不成为正文真相源。

边界：

- 需要 schema 时由主控在开工时独占分配下一 migration 版本；
- 不引入独立 Vector DB；
- 不新增第二个 SearchRepository。

### Ticket R2：章节提交后的局部索引维护

目标：

- `ChapterRepository.save_content()` 继续负责正文 revision 与依赖失效；
- 开工前先审计人工编辑、AI 接受、修复应用和导入写入路径，复用一个现有提交边界；
- 若不存在安全的统一边界，先提出最小 `submit_revision(request) -> RevisionImpact`
  应用协调合同，禁止在多个调用点分别补一套索引更新；
- 应用层在成功提交后只重建 `RevisionImpact` 指明的受影响章节；
- 旧 revision chunk/embedding/FTS fail closed；
- 崩溃或 provider 失败时保留“正文已保存、索引待重建”的可恢复状态；
- 不因一章修改重建整本书。

正式启用自动重建前，人工编辑、AI 接受、修复应用和导入必须全部走同一影响投影。

### Ticket R3：Evidence Facade 与精确回源

目标：

- 增加统一 `query_subject_evidence` / Formal Manuscript Evidence request；
- 合并 lexical、embedding、subject/alias/metadata route；
- hydrate 命中 chunk 的精确原文与必要邻接范围；
- 返回 provenance 完整的 `EvidenceSet`；
- 没有证据时显式返回 NOT_FOUND/insufficient evidence。

`SEARCH_MEMORY` 的无边界 LIKE fallback 不得成为正式证据路径。

### Ticket R4：Context Compiler 与 Retrieval Trace

目标：

- Historical Detail、Exact Quote、Existence Check 等 evidence need 可触发 RAG；
- Evidence 进入 Writer 前重新经过 authority/time/view/revision/stale 校验；
- Exact Evidence 只在当前 run 常驻；
- Manifest 记录 source range、routes 与诊断分数；
- 旧 Manifest v1/v2 继续可读；如需新字段必须单独设计兼容 envelope。

### Ticket O1：Occurrence 与 Participant Link 基础

目标：

- 一个共享事件只有一个 Occurrence；
- 多个 Subject 通过 Link 参与；
- Link 只保存 role + 短 subject projection；
- Occurrence/Link 初始只允许人工或 REVIEW 候选进入，禁止模型直接写权威记录；
- 不改变现有 Character State、Clue、Canon 的真相职责。

Occurrence 不自动等同于 `SubjectType.EVENT`。是否扩展 Subject Registry 必须由 S0 根据
查询、View target 和身份合并需求单独决定，不能为了建 Link 顺手扩大 Subject 类型。

若需要 schema，必须等待 R1 的 schema owner 释放后再开工。

### Ticket O2：Occurrence 来源修订与依赖失效

目标：

- source chapter revision 变化时 Occurrence 进入 STALE/NEEDS_REVALIDATION；
- Link projection 进入 STALE/REBUILD；
- 仅真实依赖该 Occurrence 的 State Event 才重新验证；
- 不物理删除历史结构，不让旧 Occurrence 继续作为当前事实。

### Ticket H1：Subject Progressive History

目标：

- `query_subject_history` 默认返回紧凑 INDEX；
- `get_occurrence` 只展开一个结构化事件；
- `query_subject_evidence` 再按需回查原文；
- 全部层级都有稳定排序、时间边界、limit 与字符/token cap；
- 默认不把全部 Occurrence 详情塞入 Character Context。

### Ticket V1：View 稀疏创建策略

目标：

- 收紧 View extraction contract；
- 正文显式可见事实不重复生成 READER_VIEW；
- 普通目击不生成 CHARACTER_VIEW；
- 仅认知差异进入 REVIEW 候选；
- Reader visibility 从当前 Formal Manuscript sequence 派生；
- 保留现有人工审查、编辑、来源修订和 fail-closed UI。

### Gate E1：综合检索与稀疏化评估

固定覆盖：

1. 七人共同事件只产生 1 Occurrence + 7 Links；
2. 没有状态变化的 Participant 不产生 State Event；
3. 普通目击不产生 View；
4. 正文显式信息不重复产生 Reader View；
5. 后文揭晓不污染前文；
6. Subject 历程默认只返回 compact index；
7. 一个事件可按需展开，再按需回查正文；
8. 精确关键词由 lexical route 命中；
9. 同义表达可由 embedding route 命中；
10. 候选稿、旧 revision、未来章节和 stale chunk 不得成为当前证据；
11. Exact Quote 必须来自 Formal Manuscript range；
12. 无证据时不得从摘要复原或编造；
13. 单章修改只局部重建；
14. Embedding 模型/维度变化不得无标识混用。

## 7. 依赖顺序

```text
S0 semantic audit
├── R1 chunk index
│   → R2 incremental maintenance
│   → R3 evidence facade
│   → R4 compiler/manifest trace
└── O1 occurrence foundation
    → O2 revision invalidation
    → H1 subject progressive history
        ↘ uses R3 evidence facade

V1 sparse View policy
→ depends on S0 and Formal Manuscript visibility contract

R4 + H1 + V1
→ E1 consolidated evaluation
```

R1 与 O1 若都需要 migration，不得并行持有 schema；版本号在具体票启动时由主控分配。

## 8. 明确不做

- 不创建第二套 RAG 数据库、第二个 Context Compiler 或第二个 Subject Registry；
- 不引入独立 reranker 模型作为 V1 前置条件；
- 不默认引入 Qdrant/Milvus/Elasticsearch；
- 不让 Writer、Frontend 或 Agent 直接访问 SQLite/vector store；
- 不做完整 World Engine 或知识图谱；
- 不建立全量 Character/Reader View 矩阵；
- 不从摘要猜测缺失正文；
- 不自动把模型抽取升级为权威 Occurrence/State/View；
- 不让一次 Evidence query 永久增加后续所有 prompt；
- 不修改用户正文、数据库、备份或导出。

## 9. 停止条件

实施中如果必须出现以下任一情况，停止当前票并提交 `DesignChangeProposal`：

- 新建与 `HistoryRetriever/SearchRepository` 并行的 Retriever；
- 让 Vector Store 或 Occurrence 成为正文权威；
- 让 Agent/Writer 绕过 Context Compiler；
- 创建与现有 Subject/View/Revision/Manifest 近义重复的公共模型；
- 为每个 Subject 复制完整共享事件；
- 构建 N×N View 矩阵；
- 破坏旧 Manifest、旧项目 schema 或历史 GenerationRun 可读性；
- 无法在 bounded limit/token budget 内实现 progressive retrieval；
- 必须让前端承担 authority、time、revision 或 retrieval policy。

## 10. 完成定义

只有当真实长篇项目能够稳定完成以下闭环，才算这次补充升级完成：

```text
常驻摘要提供宏观地图
+ 结构化状态提供当前确定状态
+ Subject History 提供紧凑历程索引
+ Occurrence 提供共享事件结构
+ Formal Manuscript Hybrid Retrieval 恢复历史细节
+ Exact Evidence 回源当前有效正文
+ Context Compiler 重新验证并编译
+ Manifest/Trace 解释为什么召回、为什么选入或排除
```

同时满足：

- 数据量不会随参与人数形成事件副本或 View 矩阵爆炸；
- 修改正文后旧事件投影、旧 chunk、旧 embedding 和旧 evidence 全部可检测失效；
- 摘要遗漏不等于事实不存在；
- Agent 找不到证据时明确承认不足，而不是补写历史。
