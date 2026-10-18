# AI Novel Studio 小说 Agent 与 Harness 总体设计 v0.3

> **状态：架构基线（55 项决策已锁定；已与后端“修订版 3 · Harness 集成版”对齐；补充生产级 Prompt Compiler、小说最高提示词、知识库操作契约与 Agent 上下文状态栏）**
> **用途：产品、后端、Harness、前端与 Codex 实施的共同权威文档**
> **核心原则：作者最终控制、正文安全、单一领域权威、单一运行编排权、可追溯、可恢复、按需上下文、可扩展但不提前铺摊子**
>
> **v0.3 增补：**在 v0.2 后端对齐基础上，正式加入缓存友好的 `PromptCompiler`、`CachePlan`、`ModelRequestManifest`、长篇正文分层装包策略、Agent 行为示例体系、`ProjectConstitution`（小说最高提示词）、自然语言知识库修改、Subject 合并事务、`AgentContextStatusProjection` 与上下文优化交互，以及这些能力与 Backend Domain Kernel 的所有权边界。

---

## 0. 文档约束力

本文件是 Agent 与 Harness 的架构权威，不是普通建议。

任何实现阶段都必须：

1. 先只读审计仓库；
2. 生成文件级实施票据；
3. 明确允许修改范围、禁止事项、迁移、验收与回滚；
4. 如设计与仓库冲突，提交 `DesignChangeProposal`；
5. 先更新本文件形成新版本，再修改代码；
6. 未通过真实小说项目端到端闭环，不得宣布阶段完成。

Codex 不得因“现有代码更方便”而私自建立第二套记忆、第二套正文权威链、绕过审批，或让模型直接写正式数据库。

---

# 一、产品目标与非目标

## 1. 产品目标

AI Novel Studio 的 Agent 是一个围绕长篇小说工作的、可调用工具与 Skill 的受控创作 Agent。它需要：

- 理解作者自然语言意图；
- 检索正文、记忆、计划、人物状态与证据；
- 辅助商讨、规划、局部修改、整章生成与审校；
- 构建受控 `GenerationPackage`；
- 调用独立正文生成模型；
- 将输出保存为候选稿，而非直接覆盖正文；
- 生成 Diff、ChangeSet 与审批卡；
- 在作者批准后执行正式写入；
- 管理 Run、检查点、取消、恢复、重试、用量与诊断；
- 按需发现工具和 Skill；
- 在长期会话中进行可回溯、结构化的上下文压缩；
- 通过自然语言提出受控的知识库修复、主体合并与项目规则更新；
- 根据作者已确认的讨论生成并版本化“小说最高提示词”；
- 以稳定前缀、动态后缀和确定性序列化提高提示词缓存命中率。

目标分工：

```text
AI：承担约 70%～80% 的执行、整理、检索、初稿与检查
作者：保留最终创作判断、采用权与精修权
```

## 2. 非目标

首版不追求：

- 永久运行的多 Agent 蜂群；
- 模型直接写数据库；
- Prompt 或 Skill 绕过程序权限；
- 自动补完作者明确“没想好”的剧情；
- 自动把网络资料升级为小说正典；
- 自动文学评分替作者决定版本；
- 任意 Shell、任意代码执行、整机文件访问；
- 完整插件市场与自动依赖安装；
- 同时实现 V1、V1.1、V1.2 的全部功能；
- 让 Harness 保存第二套人物卡、正典、关系、计划、Writing Profile 或主体别名真相；
- 让 Agent 通过删除一张卡片的方式伪装成“合并主体”；
- 把小说最高提示词、Harness System Prompt、Writing Profile 和当前章要求混成一个不可版本化的大文本框。

---

# 二、领域权威与总原则

## 3. 一主体、多视图、限定比较空间的权威链

小说领域主体保存可追溯事实、状态和派生快照，但**不持有任务级 Context Projection**：

```text
Subject
├── CanonProfile / CanonFacts
├── StoryStateEvents
├── ViewAssertions
├── KnowledgeStates
├── RelationshipStates
├── ChapterAppearances
└── CurrentSnapshot（派生缓存）

AgentRun
└── ContextCompilation
    ├── ContextProjection（任务产物）
    └── ContextManifest（审计产物）
```

视图：

```text
WORLD_TRUTH
CHARACTER_VIEW
READER_VIEW
AUTHOR_PLAN
```

Authority 不是一条可以跨所有记录机械比较的全局排行榜。比较前必须先确认记录处于同一比较空间：

```text
相同 semantic_scope
+ 相同 view_type
+ CHARACTER_VIEW 时相同 viewer_subject_id
+ story_time / narrative_sequence 可比较
→ 才比较 authority、revision、source 与 review_status
```

建议的 Authority 语义：

```text
APPROVED
DIRECT_EVIDENCE
DETERMINISTIC_DERIVED
REVIEW
INFERRED
```

`LOCKED` 优先建模为独立的修改策略：

```yaml
record:
  authority: APPROVED
  locked: true
```

它表示“系统不得自动修改”，不表示该记录可以覆盖其他 View、其他时间或其他语义范围的事实。

典型规则：

```text
AUTHOR_PLAN 与 WORLD_TRUTH
→ 分层保存，不直接互相覆盖

不同 CHARACTER_VIEW
→ 可以同时成立

正式正文改变计划结果
→ 计划标记 NEEDS_REVIEW，而不是反向覆盖正文
```

系统必须区分三类时间：

```text
Story Time          小说世界中的时间
Narrative Sequence  正文向读者展示信息的顺序
Run Time            模型调用、工具、审批和事件发生的真实运行时间
```

长期不变量：

```text
CANON != PLAN
工作稿 != 正式正文
聊天摘要 != 小说事实
候选 != 已批准数据
ContextProjection != 真相源
相关性 != 权威性
UNKNOWN != UNAWARE
```

## 4. 模型只提案，程序负责执行

模型只能返回：

- `OperationProposal`
- `PlanCandidate`
- `MemoryCandidate`
- `ChangeSet`
- `ConflictCase`
- `SkillChangeProposal`
- `PromptChangeProposal`
- `TodoCandidate`

后端负责 Schema 校验、权限、修订、冲突、Diff、审批、幂等执行和事件记录。

### 4.1 唯一权威与依赖方向

```text
Frontend
  ↓ 命令 / UI 投影
Agent Harness / Application Orchestration
  ↓ 稳定的 Backend Public Facades
Backend Domain Kernel
  ↓
Repositories / SQLite / Search Infrastructure
```

权威边界：

```text
Backend Domain Kernel
→ 小说真相、正文修订、状态、计划、检索与正式变更的唯一权威

Agent Harness
→ AgentRun、模型调用、Tool/Skill 调度、审批等待、取消与恢复的唯一编排权威

Frontend
→ 只消费投影并发出命令，不自行推断正式领域状态

Main Agent Model
→ 分析、调用工具、提出操作

Chapter Draft Model
→ 只生成候选正文
```

禁止依赖：

```text
Domain Backend → import Harness
Tool → 直接访问 Repository / SQLite
Frontend → 直接调用模型
Agent Model → 直接写数据库
Chapter Draft Model → 自行检索项目
```

---

# 三、总体架构

```text
Frontend
  ├─ Chat
  ├─ Editor
  ├─ Draft Candidate
  ├─ Approval
  ├─ Process Timeline
  └─ Recovery Center
        │
        ▼
Agent Harness Runtime
  ├─ Run Engine
  ├─ Context Orchestrator
  ├─ Tool Registry / Tool Search
  ├─ Skill Catalog / Loader
  ├─ Permission Gateway
  ├─ Checkpoint / Recovery
  ├─ Model Adapter / Streaming
  ├─ Usage Meter
  ├─ Artifact Store
  └─ RunEvent / Projections
        │
        ├───────────────┐
        ▼               ▼
Main Agent Model   Chapter Draft Model
        │               │
        └───────┬───────┘
                ▼
Domain Backend
  ├─ Manuscript
  ├─ Subject / View / Time / Authority
  ├─ Plan / Memory / State
  ├─ Context Compiler
  ├─ ChangeSet
  └─ Provenance / Index
```

---

# 四、双模型职责

## 5. Main Agent Model

负责：

- 任务理解与提问；
- Skill 选择；
- 工具发现与调用；
- Context Compiler 请求；
- 证据分析；
- 章节计划；
- `GenerationPackage`；
- 正文审校；
- Diff 与 ChangeSet；
- Prompt、Skill、记忆和待办提案；
- 结构化上下文压缩。

不得：

- 直接写正式数据；
- 绕过 Harness 调工具；
- 自动安装扩展；
- 自我批准任何长期修改；
- 把推测伪装成事实。

## 6. Chapter Draft Model

只负责：

- 根据 `GenerationPackage` 写整章或指定场景；
- 根据精确返工指令做一次针对性重写。

默认无权：

- 自行检索项目；
- 调工具；
- 读取完整项目聊天；
- 修改数据库；
- 更新人物状态；
- 决定采用；
- 补全明确未决剧情。

## 7. Harness

负责：

- 创建与冻结 Run；
- 模型调用；
- Tool / Skill 发现和加载；
- Permission Gateway；
- 上下文装配与压缩；
- 流式接收与候选稿检查点；
- Token、耗时、费用；
- 取消、重试、恢复和幂等；
- 强类型事件与 UI 投影；
- 审批；
- Artifact；
- 版本冻结。

---

# 五、自主权、提问与自然语言交互

## 8. 风险自适应自主权

| 风险 | 示例 | 默认行为 |
|---|---|---|
| 低 | 读取、检索、确定性检查 | 自动 |
| 中 | 草稿、建议、候选、局部 Diff | 自动生成，不永久写入 |
| 高 | 正式正文、人物状态、关系、伏笔、计划 | 作者确认 |
| 极高 | 批量改写、删除、正典覆盖、回滚 | 影响说明 + 二次确认 |

## 9. 何时提问

- 拼写、格式、基础润色：直接做；
- 局部节奏、对话：先诊断，必要时问一个关键问题；
- 人物重大转折、关系里程碑、世界规则：给选项并等待；
- “没想好”“……”：转入讨论，禁止补全；
- 低风险歧义：可用显式 Run 临时假设继续。

## 10. 提问节奏

```text
识别缺失
→ 分析依赖
→ 找出根问题
→ 每轮问 1～3 个
```

作者可切换：

```text
逐个问我
一次列出全部问题
先按合理假设继续
暂停任务
```

## 11. 单一自然语言入口

前端不要求手动切换 DISCUSS / PLAN / EXECUTE / REVIEW。
Harness 内部维护：

```text
DISCUSSING
PLANNING
EXECUTING
REVIEWING
WAITING_APPROVAL
COMPLETED
```

## 12. 运行中追加要求

提供显式操作：

```text
追加要求
修正方向
停止任务
```

- 模型未开始：吸收后重编译；
- 模型正在生成：不能假装实时注入，可完成后处理、停止重启或保留残稿；
- 正在审校：加入审校和返工；
- 等待审批：创建新候选修订。

---

# 六、会话、工作区与上下文压缩

## 13. 会话组织

V1：

```text
Project Conversation
└── AgentRun
```

后续演进为项目内主题工作区：

- 正文写作；
- 剧情；
- 人物；
- 世界观；
- 审校。

各工作区有独立历史、摘要、焦点、固定引用与 Run 列表，但共享同一个正式小说后端。

## 14. Agent State Capsule

```yaml
agent_state_capsule:
  run_id: run_...
  goal: ...
  stage: CONTEXT_COMPILED
  active_chapter_id: ...
  editor_snapshot_revision: ...
  formal_revision: ...
  context_manifest_id: ctx_manifest_...
  conversation_summary_revision: 12
  last_model_request_manifest_id: req_manifest_...
  context_health: HEALTHY
  optimization_status: OPTIMIZED
  plan: []
  assumptions: []
  pending_approvals: []
  unresolved_questions: []
  loaded_skills: []
  loaded_tools: []
  context_budget: ...
```

用途：UI、恢复、压缩、模型切换、重连。`AgentStateCapsule` 是运行事实快照，不直接作为前端展示模型；前端应消费由其与 Manifest、Event Log 共同派生的 `AgentContextStatusProjection`。

## 15. 逻辑上下文与物理 Prompt Assembly 必须分开

逻辑上，Agent 需要以下六类上下文：

```text
System / Persona / Program Policy
Agent State Capsule
最近对话原文窗口
结构化滚动摘要
Context Compiler 小说任务投影
当前任务按需 Skill、工具定义与结果摘录
```

但这六类内容**不得按上述逻辑清单直接拼接成 API 请求**。物理请求必须由 `PromptCompiler` 按稳定性重新排序：

```text
A. Global Stable Prefix
   Harness 基础身份与通用规则
   固定输出协议
   少量稳定 Agent 行为示例
   核心工具定义或稳定工具指纹

B. Project Stable Prefix
   ProjectConstitution / 小说最高提示词
   项目 Persona 与长期工作规则
   稳定项目术语
   项目级行为规则与轻量 Skill 目录

C. Run-stable Task Block
   当前任务目标与类型
   冻结的 EditorSnapshot 引用
   GenerationProfile / AuditPolicy
   当前 Run 加载的完整 Skill
   当前 Run 加载的扩展工具 Schema
   固定输出 Schema 与 Run Override

D. Dynamic Context Suffix
   结构化会话摘要
   最近对话原文
   ContextProjection
   Agent State Capsule
   最新工具结果摘录
   假设、未决问题与审批状态

E. Current Input
   最新用户指令、工具结果、审批决定或返工指令
```

原则：

- 稳定、可复用、体积较大的内容放前面；
- 频繁变化的状态放后面；
- 最新指令位于最末端；
- `AgentStateCapsule` 是动态状态，不得紧跟 System Prompt；
- 工具在 Provider API 中即使使用独立 `tools` 字段，也必须固定名称、Schema、顺序和 Revision；
- Provider 的服务器续接能力只是传输优化，本地必须能够从 Event Log、Revision 和 Artifact 重建逻辑请求；
- 任何缓存优化都不能改变消息角色优先级、工具调用配对或审批语义。

### 15.1 PromptComponent 与 CachePlan

```yaml
prompt_component:
  id: project-constitution
  kind: PROJECT_CONSTITUTION
  role: DEVELOPER
  stability: PROJECT        # GLOBAL | PROJECT | RUN | TURN
  revision: 7
  content_hash: sha256:...
  ordering_priority: 200
  cache_eligible: true
  sensitive: false
```

```yaml
cache_plan:
  provider: generic
  global_prefix_hash: sha256:...
  project_prefix_hash: sha256:...
  run_prefix_hash: sha256:...
  explicit_breakpoints: []
  cache_key: ...
  cache_retention: provider_default
```

同一 Revision 必须产生确定性的稳定前缀字节序列：

- 组件顺序固定；
- JSON 字段顺序规范化；
- 换行与编码统一；
- 核心工具顺序固定；
- 示例顺序固定；
- 不在稳定前缀写入当前时间、Run ID、章节号、Token 余量或随机追踪值；
- MCP 返回的工具列表先按稳定键排序，再冻结到 Run；
- 内容相同但 Hash 不同视为实现错误。

### 15.2 ModelRequestManifest

每次模型请求都保存本地清单，但不要求把清单全文发送给模型：

```yaml
model_request_manifest:
  request_id: req_...
  run_id: run_...
  step_id: step_...
  role: AGENT | CHAPTER_DRAFT | COMPACTION
  provider: ...
  model: ...
  prompt_revision: ...
  project_constitution_revision: ...
  project_policy_revision: ...
  writing_profile_revision: ...
  toolset_revision: ...
  skill_revisions: []
  editor_snapshot_revision: ...
  context_manifest_id: ...
  conversation_summary_revision: ...
  global_prefix_hash: ...
  project_prefix_hash: ...
  run_prefix_hash: ...
  source_artifacts: []
  input_token_estimate: ...
  cached_input_tokens: ...
  cache_status: ACCURATE | ESTIMATED | UNKNOWN
```

用途：复现、诊断、缓存分析、成本统计、审计“模型当时看到了什么”，以及判断检查点能否复用。

### 15.3 长篇正文装包策略

正式正文永远完整保存；模型每次获得的是任务专用 `ContextProjection`。长篇采用：

```text
远处剧情 → 全书/分部/剧情线/章节摘要与事件索引
近期剧情 → 最近场景和若干相关章节全文
当前工作区 → 当前选区、周围原文或当前章全文
关键旧内容 → 按需召回精确原文证据
长期一致性 → Subject / View / Time 结构化状态
文风 → 任务相关的原文 Style Exemplars
```

Token 不足时的最低优先级顺序：

```text
1. 当前任务与禁止项
2. 当前选区/当前场景连续性原文
3. POV 知识边界与关键结构化状态
4. Manual Pins 与关键旧章证据
5. 最近相关章节全文
6. 当前剧情线和章节摘要
7. 文风样本
8. 低置信度补充资料
```

不得先压缩掉当前场景原文，也不得用摘要替代关键对白、伏笔原句和文风证据。

Main Agent 使用“广范围压缩理解 + 局部原文 + 按需回查”；Chapter Draft Model 使用“较窄的摘要范围 + 更高比例近期原文 + GenerationPackage 硬约束”。

### 15.4 示例体系

示例分为三种，禁止混用：

```text
AgentBehaviorExample
→ 教 Main Agent 何时询问、如何提案、如何处理冲突和审批

StructuredOutputExample
→ 展示 ChangeSet、AuditFinding、ApprovalRequest 等合法结构；能用 Schema 保证时优先用 Schema

WritingStyleExemplar
→ 从正式正文动态召回，供 Chapter Draft Model 模仿文风
```

Agent 行为示例数量少、质量高、顺序固定并进入稳定前缀；正文文风样本属于动态 `StyleProjection`，不得常驻 Agent System Prompt。

## 16. 原始历史与最近窗口

`SessionEventLog` 保存完整用户消息、Agent 输出、工具调用、审批、模型调用、取消、失败、摘要版本和分支事件。

压缩只改变“下轮发给模型什么”，不删除历史。

最近若干轮、当前 Run 关键消息、最新作者纠正与审批原文必须保留。窗口按 Token 预算而非固定消息数计算。

## 17. 结构化滚动摘要

```yaml
conversation_summary:
  confirmed_decisions: []
  rejected_options: []
  provisional_ideas: []
  unresolved_questions: []
  author_preferences: []
  important_rationale: []
  active_entities: []
  source_references: []
```

采用增量压缩：

```text
旧摘要 + 上次摘要后的新事件 → 新摘要
```

禁止反复总结全部历史。

## 18. 程序骨架 + 主 Agent 压缩

```text
Harness 程序化提取不可丢字段
→ 主 Agent 整理自然语言部分
→ 固定 Schema 校验
→ 创建 SummaryRevision
```

程序确定性提取：

- 决策编号；
- 已批准/拒绝操作；
- Run 目标与阶段；
- 待审批；
- 未决问题；
- 临时假设；
- 章节与修订；
- 来源；
- Tool / Skill；
- 错误与恢复状态。

主 Agent 只整理选择理由、否决理由、讨论脉络和未沉淀偏好。

校验失败继续使用旧摘要。

## 19. 压缩触发与禁区

触发：

- 接近上下文预算；
- Run 完成；
- 阶段结束；
- 主题、章节、工作区切换；
- 作者主动要求；
- 空闲期。

禁止在以下状态强压缩：

- 模型流式生成中；
- 工具调用未闭合；
- 审批不稳定；
- 事务提交中。

## 20. 工具结果压缩

```text
完整工具结果 → Artifact
模型上下文 → 关键摘录 + 结构化摘要 + artifact_id
```

小说事实始终由 Context Compiler 从正式数据构建，聊天摘要不能成为领域权威。

---

# 七、Context Compiler

## 21. 定位

Context Compiler 是小说领域受约束混合 RAG，也是**所有正式生成上下文的唯一编译入口**：

```text
Task Analysis
→ Scope / Revision / View / Story Time / Narrative Sequence Hard Filter
→ Deterministic Base Context
→ FTS5 / BM25 Recall
→ Embedding Recall
→ Subject / Thread / Continuity Recall
→ Task-aware Rerank
→ Authority Resolution（仅在可比较空间内）
→ Contradiction Handling
→ Deduplication
→ Token Budget Competition
→ Context Projection
→ Context Manifest
```

硬过滤必须先于语义召回和重排。未来信息、错误 View、无效 Revision、STALE 冲突项和明确禁止内容，不应先被召回后再依赖模型“自行忽略”。

## 22. 基础上下文

优先加入：

- 当前章节或选区；
- 工作稿与正式稿修订；
- 故事时间；
- 涉及人物；
- 当前状态；
- 知识边界；
- 关系状态；
- 高权威设定；
- 已批准章节要求；
- 禁止事项；
- Writing Profile 与人物规则。

Agent 可发现远距离章节、相似互动、伏笔源头、关系证据、风格样本和作者固定引用，但不能自己成为第二个 Context Compiler。

```text
Agent / Skill 通过 subject.query、memory.query、plan.query 发现资料
→ 提交 ContextExtensionRequest 或 ManualPin
→ Context Compiler 重新执行 View / Time / Authority / Revision 校验
→ 生成新的 ContextProjection 与 Manifest
→ 才能进入 GenerationPackage
```

直接查询工具可以用于回答、诊断、探索和证据查看；凡要进入正式章节生成，必须重新经过 `context.compile`。

## 23. 硬约束

- Story Time 与 Narrative Sequence 双边界；
- 人物视角与知识边界；
- `UNKNOWN` 与明确 `UNAWARE` 分离；
- PLAN/CANON 分离；
- Authority 只用于可信门槛、同空间冲突裁决与同类 tie-breaker；
- Authority 不作为“越权威越相关”的简单相关性分数；
- 被拒绝内容排除；
- 去重；
- 单次模型调用的 Context Window / Token Budget；
- `source_revision` / `source_hash`；
- STALE 检测；
- 未来信息硬过滤。

角色知识缺少记录时，系统只能标记 `UNKNOWN`；只有存在明确证据或作者规则时，才能标记 `UNAWARE` 并作为禁止角色知道的约束。

## 24. Context Manifest

```yaml
context_manifest:
  compiler_version: ...
  task_type: ...
  story_time: ...
  view: ...
  included_sources: []
  excluded_sources: []
  authority_decisions: []
  assumptions: []
  token_breakdown: []
  source_revisions: []
```

普通 UI 显示“AI 看到了什么、额外参考、排除项、假设”；完整 Manifest 折叠展示。

---

# 八、资料摄取与记忆

## 25. 分层摄取

```text
原始资料
→ Document Role
→ Parse / Chunk / Index
→ 按角色生成记忆、计划、候选或仅索引
→ Context Compiler
```

角色：

```text
FORMAL_MANUSCRIPT
APPROVED_SETTING
PLAN_REFERENCE
EARLY_DRAFT
REJECTED_MATERIAL
RESEARCH_SOURCE
STYLE_SAMPLE
INSPIRATION_NOTE
```

### 正式正文

自动分卷分章、全文索引、章节摘要、明确出场/地点/时间、修订哈希。
心理、知识、关系、情绪、伏笔解释仅生成候选。

### 已批准设定

进入正式设定；冲突创建 `ConflictCase`，不得静默覆盖。

### 未来大纲

- 确定骨架：Approved Plan；
- 备选：PlanCandidate；
- “可能、暂定”：保留不确定性；
- “没想好、省略号”：`UNRESOLVED + BLOCK_AUTOFILL`。

### 旧稿与废案

只索引，默认不进入当前正典、状态和计划。

### 研究资料

只作现实参考，不自动成为小说事实。

### 文风样本

只进入 Writing Profile 证据，不提取剧情事实。

## 26. Memory-first、Evidence-backed、Raw fallback

结构化记忆不足时：

1. Agent 可自动搜索全部 Reference Library；
2. 搜索本身无需确认；
3. 内容准备进入回答、分析、生成包或候选前，必须询问作者；
4. 展示资料角色、权威与关键片段；
5. 批准限定用途，不自动升级资料地位。

用途可选：

```text
仅本次回答
仅作灵感
加入本次生成上下文
创建 PlanCandidate
创建记忆候选
```

## 27. 长期沉淀

- 用户交互偏好：自动保存，可撤销；
- 项目工作流/文风偏好：自动保存并轻提示；
- 临时想法：只在会话摘要；
- 人物规则、剧情计划、设定补充：候选；
- CANON、状态、知识、关系、伏笔：明确确认。

每条保留来源、修订、范围、状态、权威与批准信息。

## 27.1 自然语言知识库操作

作者可以直接用自然语言要求 Agent 修复知识库，例如：

```text
“这两张人物卡其实是同一个人，合并。”
“克莉丝汀并不知道这件事，修正她的知识状态。”
“这条关系判断是模型误判，删除候选记录。”
“把刚才确认的设定整理成正式候选。”
```

统一流程：

```text
理解命令
→ 读取 Backend 证据与当前 Revision
→ 生成 DomainOperationProposal / ChangeSet
→ Backend Dry Run 与影响分析
→ 展示 Diff、冲突和引用迁移预览
→ 作者批准
→ Backend 事务提交
→ 刷新索引、投影和 STALE 依赖
→ 保存 Undo / Merge Manifest
```

Harness 不保存知识库副本，Agent 不直接拼 SQL，Tool 不直接访问 Repository。所有永久修改均通过 Backend Public Facade、`expected_revision`、审批令牌和幂等键执行。

### 27.1.1 Subject 合并

人物被错误拆成两张卡时，Agent可以提出 `SubjectMergeProposal`，但禁止自动合并：

```yaml
subject_merge_proposal:
  primary_subject_id: char_eric_001
  duplicate_subject_ids:
    - char_lord_017
  canonical_name: 艾瑞克·冯·温德米尔
  aliases_to_preserve:
    - 白鸦镇领主
  references_to_move:
    chapter_appearances: 18
    state_events: 7
    view_assertions: 4
    relationships: 6
  field_conflicts: []
  expected_revisions: {}
  reversible: true
```

后端提交必须：

- 保留稳定主 `subject_id`；
- 将重复卡转换为 alias、redirect 或 tombstone，而不是静默物理删除；
- 迁移明确引用并生成 `MergeManifest`；
- 对同一语义范围中的冲突字段要求作者选择；
- 重建 Subject、FTS、Embedding 与依赖投影；
- 支持撤销；
- 禁止把两个相似但不同的人物只因模型高置信度而自动合并。

模型可调用的工具建议仅包含：

```text
subject.inspect
subject.compare
subject.propose_merge
subject.preview_merge
```

真正提交由审批解决器调用后端 `commit_subject_merge(...)`，不作为无条件模型写工具暴露。

---

# 九、Tool、Skill 与 MCP

## 28. 概念区分

```text
Tool  → 单个可执行能力
Skill → 可复用任务方法、流程、上下文要求、输出结构
MCP / Plugin Adapter → 外部工具、资源、Prompt 或服务的接入
```

## 29. 工具范围

V1 只允许：

- 小说领域工具；
- 受控项目文件工具；
- Artifact 工具；
- 模型调用相关工具。

默认禁止：

- 任意 Shell；
- 任意代码执行；
- 整机遍历；
- 项目外修改；
- 直接数据库写入；
- 绕过 ChangeSet；
- 无确认联网。

工具元数据：

```yaml
tool_definition:
  id: manuscript.read
  version: 1
  scope: project
  risk_level: READ_ONLY
  write_effect: NONE
  requires_approval: false
  input_schema: ...
  output_schema: ...
```

## 30. 核心工具常驻，扩展按需发现

常驻：

```text
context.compile
manuscript.read
manuscript.get_selection
subject.query
plan.query
memory.query
project_constitution.read
artifact.read
tool.search
```

知识库写操作属于扩展高风险工具面：

```text
subject.inspect
subject.compare
subject.propose_merge
subject.preview_merge
knowledge.propose_changeset
project_constitution.propose_revision
```

提交操作默认不作为普通模型工具暴露，由审批解决器调用 Backend Facade。

扩展工具只在目录中保留轻量描述；需要时：

```text
识别任务
→ 核心工具
→ 能力不足
→ tool.search
→ 加载少量 Schema
→ Permission Gateway
→ 调用
```

运行中冻结 Tool Schema 与 Provider 版本。

## 31. Permission Gateway

每次调用检查：

- 是否安装与启用；
- 项目/Run 范围；
- 风险级别；
- 路径范围；
- 是否需要确认；
- 写入影响；
- `expected_revision`；
- `idempotency_key`；
- 调用来源 Skill；
- 当前 Run 状态。

Prompt 和 Skill 不能绕过。

## 32. Skill 发现与加载

基础上下文只放：

```yaml
skill_catalog_entry:
  id: chapter_audit
  description: 检查章节事实、人物状态和知识边界
```

Agent 判断需要后加载完整 Skill：

```yaml
skill:
  id: chapter_audit
  instructions: ...
  context_requirements: ...
  recommended_tools: ...
  output_schema: AuditReport
```

Run 完成后卸载完整内容，只保留记录。

V1.1 不做复杂 Skill 冲突图、版本求解和自动依赖安装。

## 33. Skill 权限与修改

Skill 只能改变方法、检查项、输出结构、推荐工具和上下文配方，不能改变系统权限。

Agent 只能提出 `SkillChangeProposal`，作者可批准、编辑后批准、仅本次、保存副本或拒绝。批准后创建新版本，不原地覆盖。

## 34. 外部扩展

Agent 可建议扩展，但不能自行下载、安装、启用或扩权。

状态：

```text
INSTALLED
ENABLED_GLOBAL
ENABLED_PROJECT
ENABLED_RUN
```

V1.2 支持本地 Skill 与手动 MCP 配置，不做扩展商店。

---

# 十、模型、Prompt、Persona 与 Writing Profile

## 35. 双逻辑角色

```text
Agent Model
Chapter Draft Model
```

可映射同一 Provider/模型，但逻辑与记录必须分离。

更换模型只影响新 Run；历史 Run 保留模型、参数、Prompt、Skill、Writing Profile、Harness 版本。

不自动切换备用模型。

## 36. Persona 与 Writing Profile 分离并统一 Style Engine

```text
Agent Persona   → Agent 如何与作者交流
Writing Profile → 作者与 Harness 看到的正文风格领域对象
Style Engine    → 后端对 Writing Profile 的结构化实现与检索投影
```

`WritingProfile` 不得在 Harness 中再保存一套与后端平行的“文风记忆”。推荐映射：

```text
WritingProfile
├── StyleProfile
├── StyleRules
├── NegativeRules
├── PinnedExemplars
├── ExcludedExemplars
└── SceneStyleOverrides

Style Engine
→ StyleProjection
→ GenerationPackage
```

Run 只冻结：

```text
writing_profile_revision
style_projection_id
```

Generation Package 获得的是任务专用 `StyleProjection`，不会把 Agent Persona 的口吻带入正文模型。

## 37. Harness System Prompt

Harness System Prompt 定义跨小说项目通用的 Agent 行为，支持原始/结构化视图、历史、恢复出厂、导入导出和 Preset。

Run 固定 `PromptRevision`。程序安全不写在 Prompt 里，Prompt 不能改变 Tool 权限、审批要求、CANON/PLAN 分离或数据库写入规则。

## 37.1 ProjectConstitution：小说最高提示词

“小说最高提示词”是一等、版本化的项目领域对象，必须与 Harness System Prompt、Writing Profile 和当前章要求分离：

```text
Harness System Prompt
→ 跨项目 Agent 通用规则

ProjectConstitution
→ 当前小说的最高创作宪法

WritingProfile / StyleProjection
→ 正文表达和文风规则

GenerationPackage
→ 当前章节任务与硬约束
```

推荐结构：

```yaml
project_constitution:
  project_id: ...
  revision: 3
  shared_creative_rules: []
  agent_only_rules: []
  writer_only_rules: []
  overridable_rules: []
  non_overridable_rules: []
  source_decisions: []
  unresolved_exclusions: []
  approved_by_author: true
```

放置规则：

```text
稳定 Harness 规则
→ ProjectConstitution
→ 项目稳定规则与示例
→ Run 内容
→ 小说摘要、近期原文和结构化状态
→ AgentStateCapsule
→ 当前指令
```

它位于小说内容区之前，并进入 Project Stable Prefix。正文模型只接收与创作相关的 `shared_creative_rules + writer_only_rules`，不接收工具、审批和恢复规则。

作者与 Agent 讨论形成大致思路后，可以要求：

```text
“根据刚才已经确认的内容，生成小说最高提示词。”
```

Agent 必须输出 `ProjectConstitutionProposal`，列明：

- 依据的已确认决定；
- 未纳入的临时想法；
- 尚未解决的空白；
- 与现有版本的 Diff；
- 可能改变的 Agent 与正文模型行为。

作者批准后才创建新 `ProjectConstitutionRevision`。旧版本保留，可比较、恢复和导出。

### 37.1.1 Run Override

作者可对当前章节明确覆盖可覆盖规则：

```yaml
run_override:
  base_project_constitution_revision: 3
  scope: current_chapter
  overrides:
    - rule_id: tone.default
      value: 压抑克制
  approved_by_author: true
```

Run Override 不改写最高提示词，只在限定作用域内生效；不可覆盖程序安全规则或标记为 `non_overridable` 的项目原则。

## 38. Prompt 与 ProjectConstitution 修改

Agent 只能提出 Diff；作者批准后创建新版本。不能自我批准、扩大工具权限，也不能把会话中的临时构想偷偷写入最高提示词。

---

# 十一、章节计划、生成与返工

## 39. 章节计划按决策密度

- 章节卡完整：补充执行细节并生成；
- 事件明确、结构缺失：简化场景计划；
- POV、重大转折、关系、关键线索：给 2～3 个结构；
- 大量关键空白：讨论，不调用正文模型。

## 40. PlanCandidate

状态：

```text
EXPLORING
SHORTLISTED
APPROVED
REJECTED
ARCHIVED
SUPERSEDED
```

层级：

```text
StoryPart → StoryArc → PlotThread → ChapterPlan → ScenePlan
```

`APPROVED PLAN != CANON`。

## 41. Generation Package

```yaml
generation_package:
  chapter_id: ...
  editor_snapshot: ...
  formal_revision: ...
  generation_profile: QUICK | NORMAL
  audit_policy: MINIMAL | STANDARD
  goal: ...
  must_happen: []
  forbidden: []
  scene_plan: []
  pov: ...
  story_time: ...
  narrative_sequence_boundary: ...
  involved_subjects: []
  character_states: []
  knowledge_boundaries:
    known: []
    unaware: []
    unknown: []
  non_revealable_constraints: []
  relationship_boundaries: []
  project_constitution_revision: ...
  project_constitution_projection_id: ...
  writing_profile_revision: ...
  style_projection_id: ...
  references: []
  assumptions: []
  unresolved: []
  context_manifest_id: ...
```

确认策略：

- 明确、低风险：自动生成；
- 少量低风险缺口：Run 临时假设并显著展示；
- 重大转折/关系/设定/分支：等待确认；
- “没想好”或重大缺失：禁止调用正文模型；
- 可开启“生成前始终确认”。

## 41.1 快速、普通与深度审校契约

用户只看到两种生成模式：

```text
快速 → GenerationProfile.QUICK + AuditPolicy.MINIMAL
普通 → GenerationProfile.NORMAL + AuditPolicy.STANDARD
```

深度审校是对已有草稿或正文单独执行的动作：

```text
AuditPolicy.DEEP
```

它不是第三种生成模式。Agent 和 Skill 不得自行创造新的隐式档位。`GenerationProfile` 控制上下文准备和生成成本，`AuditPolicy` 控制生成后的检查深度。

## 42. 流式正文

写正文的是 Chapter Draft Model，管理输出的是 Harness。

```text
Model Stream
→ Independent Draft Candidate
→ Stable Checkpoints
→ Complete Candidate
→ Agent Audit
→ ChangeSet / Approval
```

正式编辑器不接收未完成流。

中断后提供：

```text
保留残稿
从头重写
基于残稿重新规划
参考残稿但重写未完成场景
```

不默认从半句话续写。

## 43. 返工

- 拼写、格式、明确事实错误：Agent 局部 Diff；
- 轻微表达：Agent Patch；
- 场景结构、事件缺失、节奏：反馈正文模型；
- 方向、情绪、人物理解错误：停止并问作者。

默认初稿 + 最多一次自动针对性返工。

---

## 43.1 后端审校原语与 Agent 审校解释

审校采用两层职责，禁止后端和 Agent 各自重复实现一整套审校系统：

```text
Backend Audit Primitives
→ 证据检索、确定性规则、Claim 对照、时间/View/知识边界检查
→ 输出结构化 AuditFinding

Main Agent
→ 解释 Finding、合并问题、判断剧情影响
→ 建议局部 Patch、正文模型返工或询问作者
```

后端不得直接决定怎样改写正文；Main Agent 也不得仅凭 Prompt 绕过后端证据服务重新“凭感觉”检查事实。

# 十二、结果交付、Snapshot 与合并

## 44. 结果载体

| 任务 | 交付 |
|---|---|
| 拼写/局部润色 | 选区 Diff |
| 段落重写 | 候选段落 + 意图摘要 + Diff |
| 整章重写 | 独立章节候选 + 风险 |
| 新章节 | Draft Area |
| 剧情/设定 | 结构化候选卡 |
| 跨章批量 | 按章节、操作、风险拆分的 ChangeSet |

## 45. 编辑器上下文

- 有选区：附加选区；
- 无选区、有活动章：附加整章；
- 无活动章：项目与会话上下文。

使用当前工作稿，但正式状态写入仍以正式正文为依据。

## 46. Snapshot 冻结

队列和预处理阶段可更新；Context Compiler、模型或审校开始后冻结 `EditorSnapshot`。

结果：

```text
CURRENT
STALE_BUT_REBASABLE
STALE_CONFLICTED
```

## 47. 三方合并

```text
Base   = 冻结稿
Ours   = 当前作者稿
Theirs = Agent 候选
```

不相交可生成合并候选；重叠需选择、编辑或重跑。即使自动合并也不得直接覆盖正文。

---

# 十三、章节提交与状态更新

## 48. 提交流水线

```text
保存正式修订
→ 提取事件与摘要
→ 生成状态候选
→ 冲突比较
→ 风险分类
→ 自动确定性项目
→ 作者确认解释性项目
→ 更新投影与索引
```

自动仅限字数、明确出场/地点/时间、索引、修订、哈希。

人物心理、知识、关系、情绪、立场为候选。
伏笔、主题、成长、关系里程碑仅建议。
CANON、身份真相、重大设定、不可逆事件、LOCKED 强确认。

## 49. Save 与 Submit Revision 分开

`Save` 只保存工作稿，不调用模型、不更新状态。

`Submit Revision` 执行：

```text
Diff → Semantic Impact → Mark Projections
→ Re-extract Candidates → Update Index / Dependencies
```

影响级别：

```text
DIRECT_STALE
DEPENDENCY_WARNING
UNAFFECTED
```

旧投影不删除。

---

# 十四、冲突、证据与不确定性

## 50. 冲突规则

- 明确修订：新版本生效，旧版本 `SUPERSEDED`；
- 同范围不同权威：使用高权威并记录；
- PLAN 与 CANON 分层共存；
- 小而无关空白：Run 临时假设；
- 重大动机、世界规则、剧情缺口：暂停并问；
- 语义冲突：`ConflictCase`，禁止自动融合。

## 51. 证据展示

- 明确事实：简洁 + 可展开来源；
- 人物/关系/动机解释：正文证据与 Agent 推断分开，2～4 个关键证据；
- 冲突/状态/正典候选：章节、修订、故事时间、权威、原文；
- 创意方案：明确标“建议”；
- 证据不足：直接说明。

---

# 十五、Run、检查点、取消、恢复与重试

## 52. 状态机

```text
CREATED
TASK_ANALYZED
CONTEXT_COMPILED
PACKAGE_READY
MODEL_RUNNING
DRAFT_SAVED
AUDIT_COMPLETED
CHANGESET_READY
WAITING_APPROVAL
COMPLETED
```

异常：

```text
CANCELLED
INTERRUPTED
FAILED
STALE
```

## 53. 检查点

在任务分析、上下文编译、生成包、正文稳定段落、完整草稿、审校、ChangeSet、等待审批等边界创建。

复用前验证修订、Manifest、Prompt、Skill、Tool Schema、模型、参数与 Hash。

## 53.1 共享检查点基础设施

底层可共享 Artifact / Checkpoint Repository，但对象类型必须分开：

```text
RUN_CHECKPOINT
DRAFT_CHECKPOINT
DOMAIN_RECOVERY_POINT
MIGRATION_SNAPSHOT
BACKUP_SNAPSHOT
```

不得为旧 Pipeline、Agent Runtime、正文流和迁移各建一套互不相认的恢复目录。

## 54. 取消

取消后：

1. 不发新工具；
2. 请求 Provider 取消；
3. 关闭 Run 事件入口；
4. 拒绝迟到流；
5. 保存 Partial Draft；
6. 标记 CANCELLED；
7. 不自动复活。

持久操作带：

```text
run_id
operation_id
idempotency_key
expected_revision
```

## 55. 恢复中心

展示任务、中断阶段、已保存产物、可复用内容、修订一致性和可选操作。

`WAITING_APPROVAL` 必须恢复原审批界面。

## 56. 重试

自动重试仅限网络、Timeout、5xx、临时繁忙、429，默认最多两次并遵守 `Retry-After`。

- 上下文过长：重编译/压缩后一次；
- 工具参数无效：结构化纠正一次；
- 长流中断：保存 Partial 并询问；
- 认证、余额、模型缺失、越权、修订冲突、数据库错误：停止；
- 不自动换模型。

## 57. 完成校验

程序检查工具、Schema、修订、错误、产物和审批；Agent 检查请求覆盖、假设、未决问题、必须/禁止、知识边界、人物声线、时间地点与未决设定。

有正式变更待审批时必须是 `WAITING_APPROVAL`，不是 `COMPLETED`。

---

# 十六、并发、维护与待办

## 58. 并发

V1：

- 普通聊天可继续；
- 一个正式模型/工具 Run 执行；
- 程序维护可后台；
- 其他正式任务排队。

队列绑定项目、章节、工作稿修订、正式修订和任务目标，启动前重新校验。

未完成草稿永远不参与正式事实检索。

## 59. 主动维护

- 纯程序检查：自动；
- 低成本只读模型检查：可选；
- 高 Token 深审校：只提醒；
- 剧情解释和状态更新：只做候选。

禁止自动填未决剧情、改正文、批 CANON、改关系/知识、自动回收伏笔。

## 60. 待办

Agent 可提出 `TodoCandidate`，作者批准后创建。涉及剧情判断的关闭同样需确认。

---

# 十七、联网与研究

## 61. 联网前确认

Agent 可建议联网，但必须先说明搜索目的、查询主题、资料类型与用途。

作者可选择：

```text
允许本次搜索
修改范围
只用项目资料
不再建议
```

结果区分现实事实、来源观点、Agent 推断、创作建议。

## 62. 研究不沉淀

联网结果只用于当前任务，不自动保存 Research Bundle、网页或长期摘要。

可保留最小调用日志。经作者批准形成的小说计划/正文可保存，但保存的是小说成果，不是网络研究包。

---

# 十八、强类型 RunEvent 与 UI 投影

## 62.1 StoryStateEvent 与 AgentRunEvent 分离

必须在类型、表名和模块上明确区分：

```text
StoryStateEvent / story_state_events
→ 小说世界中人物、关系、位置、知识和物品的变化

AgentRunEvent / agent_run_events
→ 软件中的检索、模型、工具、审批、取消和恢复事件
```

后端“暂缓通用事件溯源 World Engine”不妨碍 Harness 对 AgentRun 使用不可变事件日志；两者不得共用模糊的 `state_events` 或 `events` 名称。

## 63. RunEvent

```yaml
run_event:
  event_id: evt_...
  run_id: run_...
  sequence: 42
  event_type: TOOL_CALL_COMPLETED
  schema_version: 1
  occurred_at: ...
  causation_id: ...
  correlation_id: ...
  payload: {}
```

事件至少包括：

```text
RUN_CREATED / STARTED / CANCELLED / INTERRUPTED / FAILED / COMPLETED
CONTEXT_COMPILATION_STARTED / CONTEXT_COMPILED / CONTEXT_INVALIDATED
CONTEXT_EXTENSION_REQUESTED / CONTEXT_RECOMPILE_REQUESTED / CONTEXT_HEALTH_CHANGED
MANUAL_CONTEXT_PIN_ADDED / MANUAL_CONTEXT_PIN_REMOVED
COMPACTION_STARTED / COMPACTION_COMPLETED
SKILL_DISCOVERED / SKILL_LOADED
TOOL_SCHEMA_LOADED / TOOL_CALL_STARTED / COMPLETED / FAILED
GENERATION_PACKAGE_READY
CHAPTER_STREAM_STARTED / DELTA / CHECKPOINT_SAVED / COMPLETED
AUDIT_STARTED / AUDIT_COMPLETED
CHANGESET_READY / REBASED / CONFLICTED
APPROVAL_REQUESTED / APPROVAL_RESOLVED
```

## 64. UI 投影

```text
ChatProjection
RunStatusProjection
DraftStreamProjection
ApprovalProjection
ProcessTimelineProjection
UsageProjection
AgentContextStatusProjection
RecoveryProjection
```

前端不得根据聊天文字自行推断领域状态。

可靠性：

- `run_id + sequence` 保序；
- 重连补发；
- `event_id` 幂等；
- Cancel 后拒绝迟到事件；
- 未知事件可忽略展示但保留诊断；
- 高频 Delta 可合并；
- 审批必须可恢复。

## 64.1 AgentContextStatusProjection

`AgentContextStatusProjection` 是面向前端的只读上下文健康投影，用于回答四个问题：

```text
Agent 当前带着哪些上下文？
上下文是否接近预算或已经过期？
哪些内容是全文、摘要、精确证据或临时固定项？
是否需要压缩、扩展或重新编译？
```

它必须由 Harness Projection Service 根据以下事实确定性生成：

```text
AgentStateCapsule
+ ModelRequestManifest
+ ContextManifest
+ ConversationSummaryRevision
+ RunEvent Log
+ Provider Usage Metadata
→ AgentContextStatusProjection
```

禁止让模型凭自然语言自报“上下文很好”“已经记住全部内容”。

推荐结构：

```yaml
agent_context_status_projection:
  projection_revision: 18
  run_id: run_...
  stage: CONTEXT_COMPILED
  active_chapter_id: chapter_...

  health:
    level: HEALTHY            # HEALTHY | WARNING | CRITICAL | RECOMPILING | UNKNOWN
    optimization_status: OPTIMIZED
    warnings: []

  budget:
    used_tokens: 48200
    budget_tokens: 100000
    usage_ratio: 0.482
    measurement: ESTIMATED    # ACCURATE | ESTIMATED | UNKNOWN

  composition:
    recent_conversation_tokens: 6200
    conversation_summary_tokens: 1800
    novel_context_tokens: 31700
    tool_result_tokens: 4200
    prompt_tool_skill_tokens: 4300

  conversation:
    summary_revision: 12
    recent_raw_turns: 8
    compaction_status: OPTIMIZED

  novel_context:
    context_manifest_id: ctx_manifest_...
    fulltext_chapter_count: 3
    summarized_chapter_count: 27
    exact_evidence_count: 6
    manual_pin_count: 1
    stale: false

  runtime:
    loaded_skill_count: 1
    loaded_tool_count: 7
    pending_approval_count: 0
    unresolved_question_count: 1

  cache:
    status: HIT               # HIT | MISS | PARTIAL | ESTIMATED | UNKNOWN
    cached_input_tokens: 19100

  provenance:
    last_model_request_manifest_id: req_manifest_...
    source_revisions: []

  available_actions:
    - VIEW_CONTEXT_DETAILS
    - REQUEST_CONTEXT_EXTENSION
    - RECOMPILE_CONTEXT
    - COMPACT_CONVERSATION
```

语义规则：

- `HEALTHY` 只表示预算、Revision、Manifest 和依赖状态正常，不代表模型一定理解正确；
- `WARNING` 表示接近预算、存在低置信度来源、摘要较旧或部分依赖待刷新；
- `CRITICAL` 表示关键 Context 已失效、当前任务缺少硬约束、预算无法容纳最低上下文，或继续运行可能产生错误结果；
- `RECOMPILING` 表示 Context Compiler 或压缩服务正在生成新投影；
- `UNKNOWN` 必须如实显示，不得伪装成健康状态；
- `stale=true` 时，正文生成和高影响修改必须重新走 Context Compiler；
- Token 与缓存统计必须标记 `ACCURATE / ESTIMATED / UNKNOWN`。

该投影不得包含隐藏思维链、模型内部推理文本、API Key、完整敏感工具输出或未经裁剪的小说资料。

## 64.2 Agent Context Status Bar

前端应提供一个低干扰的 `AgentContextStatusBar`。它是 Agent 面板中的上下文状态入口，不是新的知识库、不是第二个 Context Compiler，也不是开发者控制台。

默认只显示一行可理解信息：

```text
上下文 48% · 已优化 · 3 章原文 · 6 条关键证据 · 缓存命中
```

面向普通作者可以使用更自然的文案：

```text
AI 上下文良好　已整理对话　参考了 3 章原文和 6 条关键资料
```

显示原则：

- 位于 AI 助手标题区下方或输入区上方，始终可见但视觉权重低于当前任务和审批；
- 无活动 Run 时显示项目上下文准备状态，不伪造 Token 数；
- 小任务仅显示健康度和一句摘要；复杂任务可显示阶段、上下文比例和警告；
- 同一时刻只突出一个主动作，例如“重新编译”或“整理对话”；
- 正常状态使用中性或轻绿色；警告使用琥珀色；关键失效使用红色；重新编译使用运行态；
- 点击后展开详情抽屉，不在默认界面堆叠工程字段；
- 不与应用底部“模型 / 自动保存 / 任务”状态栏重复。

展开层至少展示：

```text
当前任务与阶段
最近对话原文窗口
结构化摘要 Revision
全文章节、摘要章节与精确证据数量
Manual Pins 与临时补充上下文
已加载 Skill 与工具数量
Context Manifest 与来源摘要
Token 构成、缓存状态、模型和调用时间
警告、过期原因与可执行动作
```

前端不得根据聊天文本猜测这些字段，也不得把 `read_selection`、`context.compile` 等内部工具名作为普通用户默认文案。高级诊断模式才可显示工具、Manifest ID、Revision 与 Hash。

## 64.3 上下文优化与重新编译交互

状态栏允许用户发起上下文管理请求，但所有操作必须通过正式命令进入 Harness：

```text
AgentContextStatusBar
→ ContextOptimizationCommand
→ AgentRunEngine / Context Coordination Service
→ Conversation Compaction 或 Backend Context Compiler
→ 新 SummaryRevision / ContextManifest / ModelRequestManifest
→ RunEvent
→ 新 AgentContextStatusProjection
```

推荐命令：

```text
VIEW_CONTEXT_DETAILS
REQUEST_CONTEXT_EXTENSION
RECOMPILE_CONTEXT
COMPACT_CONVERSATION
PIN_EVIDENCE
UNPIN_EVIDENCE
```

推荐请求结构：

```yaml
context_optimization_command:
  command_id: cmd_...
  run_id: run_...
  command: REQUEST_CONTEXT_EXTENSION
  reason: 需要回查第八章的旧港伏笔原句
  target_scope:
    chapter_ids: []
    subject_ids: []
    evidence_refs: []
  budget_policy: BALANCED
  source_projection_revision: 18
```

执行规则：

- `REQUEST_CONTEXT_EXTENSION` 只能请求扩展范围，最终资料仍由 Context Compiler 按 Scope、View、Story Time、Authority 和 Revision 校验；
- `RECOMPILE_CONTEXT` 不得复用已经失效的 ContextProjection；
- `COMPACT_CONVERSATION` 只改变后续模型输入，不删除 SessionEventLog；
- `PIN_EVIDENCE` 只能固定已有 `EvidenceRef`、明确选区或正式资料引用，不得把聊天猜测固定成 CANON；
- Manual Pin 必须显示来源、Revision、加入原因和 Token 影响，并允许解除；
- 优化过程不得在模型流式生成、工具调用未闭合、审批不稳定或事务提交中强行执行；
- 优化完成后必须产生新的 Revision / Manifest，并使旧投影进入失效或历史状态；
- 状态栏只能请求知识库修改提案，不能直接修改正文、人物、设定、计划或 SQLite。

所有权边界：

```text
Harness
→ 拥有状态栏命令、上下文协调、会话压缩、Projection 与 RunEvent

Backend Context Compiler
→ 拥有小说上下文的检索、裁剪、证据、Authority 与 Manifest

Frontend
→ 只发送命令并消费 Projection
```

状态栏的“已优化”是可验证的工程状态，不是创作质量承诺。

---

# 十九、过程可见性与用量

## 65. 分层展示

小任务显示简短状态，复杂任务显示阶段。

`AgentContextStatusBar` 默认显示上下文健康度、预算比例、资料构成与缓存状态；点击后展开来源、Manifest、Revision、Manual Pins 和优化动作。

可展开查看工具、来源、Manifest、Token、耗时、模型、修订、Skill、诊断。

不展示隐藏思维链，只展示可验证计划、动作、来源、假设、中间产物和结果。

## 66. 不设常规预算硬上限

展示：

- 输入/输出 Token；
- 缓存 Token；
- 推理 Token（可提供时）；
- Agent 与正文模型分开；
- 费用；
- 耗时；
- 调用数；
- 上下文构成。

标注 `ACCURATE / ESTIMATED / UNKNOWN`。

仍阻止无进展循环、重复调用与重复失败。

---

# 二十、记录、备份、密钥与升级

## 67. Run 保留

永久保留目标、状态、模型、Prompt、Skill、Tool、修订、Hash、Manifest、Generation Package、工具摘要、用量、产物、审批、错误和重试。

原始请求、响应、流、完整工具结果默认 30 天。创作产物和采用版本永久。Artifact 内容寻址去重。

## 68. 备份与导出

- 正文：Markdown；
- 结构化数据：SQLite；
- 大产物：Artifact Store；
- 密钥：不进项目包。

自动恢复点：提交、审批、批量修改、删除/移动/合并、迁移/升级、每日关闭。

`.aistudio-project` 包含 Manifest、Markdown、SQLite、Artifacts、Hash、Schema 与兼容信息。

## 69. API Key

明文保存在全局用户配置，项目仅引用 Credential Profile。UI/日志遮罩，Git/备份/导出排除。必须明确告知未静态加密。

## 70. 项目升级

项目配置固定；重大 Harness 行为变化需显式迁移。

作者可选择兼容模式、升级、暂不决定、查看变化。升级只影响新 Run；历史 Run 保留旧版本。

---

# 二十一、质量保障

## 71. 不做自动创作质量评测套件

不建立自动文学评分、创意 benchmark、默认盲测、模型排名门禁，或根据分析数据自动替作者选择模型。文风和剧情质量以真实创作使用、作者判断和可回滚的版本对比为准。

允许保留**非文学质量裁决型**的工程基线：

- 固定检索安全用例；
- 未来信息泄露测试；
- View / Knowledge Boundary 正确性；
- 关键事实召回与无关内容比例；
- Context Manifest 完整性；
- Token、延迟和失败率观测；
- 真实项目 Smoke Test。

这些指标用于发现工程退化，不能自动宣告某个草稿“文学性更好”，也不能成为模型或文风的强制采用门禁。

## 72. 数据正确性与检索安全必须测试

至少测试：

- 正文不静默覆盖；
- CANON/PLAN 分离；
- Tool / Skill 权限；
- Stale ChangeSet 拒绝；
- Cancel 后迟到事件拒绝；
- 三方合并；
- 备份恢复；
- 事件顺序与幂等；
- Prompt 不改变程序权限；
- 未来信息过滤；
- `UNKNOWN / UNAWARE`；
- Authority 只在可比较空间裁决；
- 直接查询工具不能绕过 Context Compiler 进入生成包；
- Revision/Hash；
- Run 重启恢复。

```text
Prose quality           → real use + author decision
Data correctness        → automated tests
Retrieval safety        → fixed regression cases
Operational reliability → integration / smoke tests
```

---

# 二十二、分阶段实施

## 73. Harness V1：完整章节闭环

必须实现：

- 单主 Agent；
- 双模型角色；
- 核心小说工具；
- PromptCompiler、CachePlan 与 ModelRequestManifest；
- Context Compiler；
- Generation Package；
- 正文独立候选流与检查点；
- Agent 审校；
- ChangeSet 与审批；
- RunEvent；
- `AgentContextStatusProjection` 与基础 `AgentContextStatusBar`；
- 取消与基础恢复；
- Token、耗时、过程展示。

V1 接线前必须冻结 Backend/Harness 共享 DTO，并确认唯一编排权：

```text
Harness AgentRunEngine
→ 唯一拥有任务阶段、模型调用、工具循环、重试、取消、流式输出、Run 检查点和审批等待

旧 Generation / Audit / Repair Pipeline
→ 降级为 Backend Facade、短事务 Use Case Service 或 Legacy Adapter
→ 不得与 AgentRunEngine 并列成为第二个总状态机
```

至少冻结：

```text
SubjectId
ViewSpec
StoryTimeBoundary
NarrativeSequenceBoundary
AuthorityScope
ContextCompileRequest
ContextProjection
ContextManifest
EditorSnapshot
GenerationPackage
AuditFinding
ChangeSet
ApprovalRequest
RevisionRef
EvidenceRef
StyleProjection
ProjectConstitutionRevision
ProjectConstitutionProposal
ProjectConstitutionProjection
SubjectInspection
SubjectMergeProposal
MergePreview
MergeManifest
AgentContextStatusProjection
ContextOptimizationCommand
ContextExtensionRequest
ManualContextPin
```

端到端门禁：

```text
打开真实旧项目
→ Agent 读取当前章节
→ Context Compiler 检索
→ 构建 Generation Package
→ 正文模型流式生成候选稿
→ 可取消并保存残稿
→ Agent 审校
→ 创建 ChangeSet
→ 作者批准
→ 保存正式修订
→ 重启软件
→ 正文、Run、审批、来源全部正确恢复
```

## 74. Harness V1.1：长期使用

- 结构化上下文压缩；
- 上下文详情抽屉、Manual Pins、扩展请求与重新编译交互；
- Skill 按需加载；
- 扩展工具发现；
- Skill 修改提案；
- 会话分支；
- 三方合并；
- 待办与维护中心；
- 完整恢复中心；
- ProjectConstitution 提案、Diff、版本与 Run Override；
- Subject 合并提案、预览、审批适配与撤销入口；
- 自然语言知识库 ChangeSet。

## 75. Harness V1.2：扩展生态

- 本地自定义 Skill；
- 手动 MCP；
- 项目级扩展权限；
- Plugin Adapter；
- 有限子 Agent；
- 重大 Harness 迁移与兼容模式。

接口可提前稳定，但禁止同时铺开全部实现。

---

# 二十三、有限多 Agent 预留

V1 只使用 Main Agent、确定性服务和 Chapter Draft Model。

未来复杂任务可临时启动 1～2 个子 Agent：

- 隔离上下文；
- 白名单工具；
- 有预算；
- 只提交提案；
- 无正式写权限；
- 主 Agent 汇总。

不建立常驻 Agent 群。

---

# 二十四、实施治理

## 76. Implementation Ticket

```yaml
implementation_ticket:
  id: HARNESS-V1-A1
  objective: 建立 AgentRun 与强类型事件骨架
  design_sections: []
  allowed_files: []
  prohibited_changes:
    - 不修改正文权威链
    - 不引入第二套记忆
  migrations: []
  acceptance_tests: []
  rollback_plan: ...
```

## 77. Design Change Proposal

```yaml
design_change_proposal:
  conflict: ...
  current_design: ...
  repository_evidence: ...
  proposed_change: ...
  affected_decisions: []
  alternatives: []
```

流程：

```text
更新设计文档
→ 新设计版本
→ 更新实施票据
→ 修改代码
```

---

# 二十五、推荐逻辑模块

```text
agent_runtime/
  run_engine
  run_state
  checkpoints
  cancellation
  retry

context/
  context_orchestrator
  conversation_window
  structured_compaction
  state_capsule
  context_manifest
  manuscript_context_packing

prompting/
  prompt_compiler
  prompt_component
  cache_plan
  model_request_manifest
  example_registry
  project_constitution_projection

tools/
  core_tools
  tool_catalog
  tool_search
  permission_gateway
  mcp_adapter

skills/
  skill_catalog
  skill_loader
  skill_change_proposal

models/
  provider_adapter
  role_binding
  streaming
  usage_meter

artifacts/
  artifact_store
  draft_candidate
  retention

approval/
  approval_request
  changeset_review
  prompt_change
  project_constitution_change
  subject_merge_review
  skill_change

knowledge_operations/
  domain_operation_proposal
  subject_merge_proposal
  knowledge_changeset_adapter

events/
  run_event
  event_store
  projections
  replay

recovery/
  recovery_center
  resumability_check
  stale_detection
```

---

# 附录 A：Backend / Harness Integration Contract 摘要

## A.1 唯一编排与唯一领域权威

```text
Harness owns orchestration.
Backend owns domain truth.
```

Harness 不持有第二套人物、记忆、计划、文风或 Context Projection 真相库；Backend 不管理聊天流、模型 Tool Loop、Skill 发现和 Run 生命周期。

## A.2 Backend Public Facades

Harness 只通过稳定应用接口访问后端，推荐最小表面：

```text
compile_context(request) -> ContextProjection + ContextManifest
query_subject_evidence(request) -> EvidenceSet
query_plan(request) -> PlanResult
build_style_projection(request) -> StyleProjection
get_project_constitution(request) -> ProjectConstitutionRevision
build_project_constitution_revision(request) -> ProjectConstitutionProposal
commit_project_constitution_revision(request, approval, expected_revision)
inspect_subjects(request) -> SubjectInspection
build_subject_merge(request) -> SubjectMergeProposal + MergePreview
commit_subject_merge(request, approval, expected_revisions) -> MergeManifest
audit_claims(request) -> AuditFinding[]
build_changeset(request) -> ChangeSet
commit_changeset(request, approval, expected_revision)
extract_state_candidates(request) -> Candidate[]
submit_revision(request) -> RevisionImpact
```

## A.3 允许并行开发的 Harness 基础设施

在后端契约冻结前可并行实现：

- AgentRun / AgentRunEvent / Event Store；
- Model Adapter / Streaming / Usage Meter；
- Draft Artifact；
- Cancel Token；
- UI Projection；
- Tool / Skill Catalog 骨架；
- PromptCompiler、CachePlan、ModelRequestManifest 的纯 Harness 实现。

必须等后端 DTO 稳定后接线：

- `context.compile`；
- Subject/View/Plan 查询；
- AuditFinding；
- ChangeSet 提交；
- 状态提取与 STALE 传播；
- StyleProjection；
- 原始资料进入生成上下文的审批；
- SubjectMergeProposal / MergeManifest；
- ProjectConstitutionRevision / Proposal 的项目存储 Facade。

---

# 附录 B：55 项锁定决策台账

| # | 主题 | 锁定结论 |
|---:|---|---|
| 01 | 自主权 | 风险自适应：低风险自动，高风险确认，极高风险二次确认 |
| 02 | 是否提问 | 按任务规模与决策密度 |
| 03 | 多 Agent | 最终有限子 Agent，V1 单主 Agent |
| 04 | 过程展示 | 自适应分层，保留可展开诊断 |
| 05 | 会话组织 | 项目会话 + Run，后续主题工作区 |
| 06 | 长期沉淀 | 分层沉淀，关键小说信息需批准 |
| 07 | 结果交付 | Diff、候选章、卡片、ChangeSet 分级 |
| 08 | 冲突与缺失 | 权威、PLAN/CANON、临时假设、ConflictCase 分开 |
| 09 | 模型配置 | Agent 模型 + 正文模型两个逻辑角色 |
| 10 | 工具范围 | 可扩展白名单，V1 小说领域与受控文件 |
| 11 | 正文返工 | Agent 审校，局部 Patch 或正文模型一次返工 |
| 12 | 生成包确认 | 按风险自适应，重大空白禁止生成 |
| 13 | 章后状态 | 确定性自动，解释性候选，关键项确认 |
| 14 | 手工修订 | Save/Submit 分开，语义失效与依赖传播 |
| 15 | 取消恢复 | Event-sourced Run + Checkpoint + 幂等 |
| 16 | 完成验证 | 程序检查 + Agent 自检 |
| 17 | 主动维护 | 事件触发、成本分层，不自动改正式数据 |
| 18 | 并发 | 最终有限并行，V1 一个正式 Run 队列 |
| 19 | 上下文选择 | Compiler 基线 + Agent 受控扩展 |
| 20 | 模式 | 单一自然语言入口，内部状态机 |
| 21 | 运行中指令 | 显式追加/修正/停止 |
| 22 | 预算 | 不设常规硬上限，展示用量，阻止死循环 |
| 23 | 重试 | 仅瞬时错误有限重试，不自动换模型 |
| 24 | System Prompt | 完整开放、版本化、可恢复 |
| 25 | Prompt 改进 | Agent 只提 Diff，作者批准 |
| 26 | 章节规划 | 按决策密度选择直写、计划、选项或讨论 |
| 27 | 计划管理 | PlanCandidate 与正式计划分离 |
| 28 | 反馈学习 | 单次本地，重复形成观察，长期规则需提案 |
| 29 | 证据展示 | 按结论类型展示 |
| 30 | 会话分支 | 分支 + 结构化结果，V1 可先手动 |
| 31 | 编辑器上下文 | 选区优先，否则当前章，否则项目会话 |
| 32 | Snapshot | 模型开始后冻结，结果检测过期 |
| 33 | Rebase | Base/Ours/Theirs 三方合并 |
| 34 | Run 保留 | 核心永久，原始大对象默认 30 天 |
| 35 | 备份 | Markdown + SQLite + Artifact + 恢复点 |
| 36 | API Key | 全局明文配置，项目只引用 Profile |
| 37 | 外部模型隐私 | 配置即允许发送任务所需内容，Manifest 记录 |
| 38 | Persona/文风 | 分离 |
| 39 | 评测 | 不建创作评测套件，数据正确性严格测试 |
| 40 | 升级 | 项目配置固定，重大 Harness 更新显式迁移 |
| 41 | 资料摄取 | 按资料角色分层 |
| 42 | 原文回退 | 自动搜全部原始资料，引用前询问 |
| 43 | 联网 | Agent 可建议，搜索前确认 |
| 44 | 网络研究保存 | 只用于当前任务 |
| 45 | 待办 | Agent 提候选，作者批准后创建 |
| 46 | 提问节奏 | 依赖驱动、自适应 1～3 问 |
| 47 | 正文流 | 正文模型写，Harness 独立候选流 + 检查点 |
| 48 | Skill 发现 | Agent 从轻量目录按需加载 |
| 49 | Skill 修改 | Agent 只提修改 Diff，作者批准 |
| 50 | 工具暴露 | 核心常驻，扩展按需发现 |
| 51 | 扩展安装 | Agent 可建议，作者安装和启用 |
| 52 | 压缩模型 | 程序骨架 + 主 Agent 结构化压缩 |
| 53 | MVP | V1/V1.1/V1.2 纵向阶段 |
| 54 | 前后端协议 | 强类型不可变 RunEvent + UI Projection |
| 55 | 实施治理 | 设计文档为权威，受控变更与实施票据 |

---

# 附录 C：当前小说资料角色示例

```text
第一部决定版正文
→ FORMAL_MANUSCRIPT

第二部简略内容指导手册
→ PLAN_REFERENCE

其中明确确定的骨架
→ Approved Plan 候选

“可能”“暂定”
→ Provisional Plan

省略号、“没想好”
→ UNRESOLVED + BLOCK_AUTOFILL
```

系统不得因为内容存在于导入文件中，就自动将其提升为 CANON。

---

# 附录 D：V1 推荐实施顺序

```text
A1  AgentRun + RunEvent + EventStore
A2  Model Role Binding + Agent/Chapter Adapter
A3  Core Tool Registry + Permission Gateway
A4  PromptCompiler + CachePlan + ModelRequestManifest
A5  Context Compiler Tool Facade + Manuscript Context Packing + Manifest
A6  GenerationPackage + Chapter Draft Stream
A7  Draft Artifact + Stable Checkpoint + Cancel
A8  Agent Audit + ChangeSet + Approval
A9  Save/Commit + Post-commit Deterministic Update
A10 Recovery Projection + Restart Resume
A11 ProjectConstitution Proposal / Revision
A12 Subject Merge Proposal / Preview / Approval Adapter
A13 Agent Context Status Projection / Status Bar
A14 Old Project End-to-End Smoke Test
```

---

# 附录 E：v0.3 生产级增补的验收测试

## E.1 Prompt 与缓存稳定性

- 同一 Prompt/Tool/Example Revision 产生相同稳定前缀 Hash；
- AgentStateCapsule、Run ID、当前时间不会污染 Global/Project Prefix；
- 工具 Schema 和示例顺序确定；
- ProjectConstitution 位于 Manuscript Context 之前；
- ContextProjection 和最新用户指令位于动态后缀；
- Provider 返回缓存统计时写入 UsageProjection；
- Provider 不支持显式缓存时仍保持通用确定性序列化。

## E.2 长篇上下文

- 当前场景原文不会被远程摘要挤出；
- 远程章节使用摘要，关键旧章能回查精确原文；
- 章节 Revision 改变后摘要和证据依赖进入 STALE；
- Main Agent 与 Chapter Draft Model 获得不同的 Context Projection；
- 摘要不能成为 CANON 来源。

## E.3 知识库修改

- Agent不能直接写 Repository/SQLite；
- Subject 合并预览展示全部引用迁移和字段冲突；
- 合并保留 alias/redirect/tombstone 和 MergeManifest；
- 合并可撤销；
- 并发 Revision 变化时提交失败；
- ProjectConstitution 提案区分已确认、临时与未决内容；
- 最高提示词修订不改变 Harness 程序权限。

## E.4 Agent 上下文状态栏

- `AgentContextStatusProjection` 由 Capsule、Manifest、Revision、Event Log 与 Usage 元数据确定性生成，不依赖模型自报；
- Context 编译、压缩、缓存命中、Manual Pin、Revision 失效后，状态栏能按 RunEvent 顺序更新；
- 页面刷新或断线重连后可恢复同一 Projection，不靠解析聊天文本重建；
- `HEALTHY` 只代表工程状态正常，不被展示为“模型已经理解全部内容”；
- Token、缓存和费用数据正确标注 `ACCURATE / ESTIMATED / UNKNOWN`；
- `stale=true` 或关键 Context 失效时，正文生成与高影响修改被阻止并要求重新编译；
- `COMPACT_CONVERSATION` 不删除原始 SessionEventLog，也不丢失审批、作者纠正和当前 Run 关键消息；
- `REQUEST_CONTEXT_EXTENSION` 与 `PIN_EVIDENCE` 不能绕过 Context Compiler、Authority 或 Revision；
- 普通模式不显示隐藏思维链、内部工具名、完整敏感工具输出或 API Key；
- 状态栏命令不能直接修改正文、知识库、计划或 SQLite。

---

# 附录 F：公开工程范式参考

本设计参考以下公开文档中的通用范式，不使用任何泄露源码：

- OpenAI Agents SDK：Session 持久化、历史输入过滤、会话压缩、Tool Search 延迟工具加载；
- LangGraph：短期/长期记忆分离、滚动摘要、Checkpoint、人工中断与故障恢复；
- Model Context Protocol：Tools/Resources/Prompts 发现、Schema 化调用、工具列表变化与用户确认；
- Claude Code 公开文档：用户、项目与局部上下文分层，嵌套资料按需加载。

这些只用于验证通用 Harness 机制。小说领域的 `Subject × View × Time × Authority`、CANON/PLAN、Context Projection、ChangeSet 与作者审批链由 AI Novel Studio 自己定义。

---

**文档结束**
