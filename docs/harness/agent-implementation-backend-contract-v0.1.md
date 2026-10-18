# AI Novel Studio Agent 实施与后端防冲突契约 v0.1

> **用途：**在 Codex 开始实现 Agent、Tool、PromptCompiler、知识库操作和小说最高提示词前，作为强制阅读的接线契约。
> **依赖基线：**《AI Novel Studio 小说 Agent 与 Harness 总体设计 v0.3》与《后端改进方案·修订版 3·Harness 集成版》。
> **目标：**防止 Agent 实施过程中建立第二套领域系统、绕开 Context Compiler、重复旧 Pipeline、直接改数据库，或把 Prompt 配置误当成小说知识库。

---

# 1. 一句话边界

```text
Harness owns orchestration.
Backend owns domain truth.
PromptCompiler owns request assembly.
Frontend owns presentation, not truth.
Models propose; deterministic services commit.
```

---

# 2. 所有权矩阵

| 对象/能力 | 唯一所有者 | Harness 能做什么 | Harness 禁止做什么 |
|---|---|---|---|
| 正式正文与 Revision | Backend | 读取、提交候选 ChangeSet | 直接覆写 Markdown/SQLite |
| Subject、别名、人物卡 | Backend | 查询、提出 MergeProposal | 保存第二套人物 Registry |
| CANON / View / State | Backend | 查询证据、提出候选 | 从聊天摘要直接写正式状态 |
| PLAN | Backend | 查询、提出 PlanCandidate | 把计划当已发生事实 |
| ContextProjection | Backend Context Compiler | 请求编译、传给模型 | 自己拼正式生成上下文 |
| WritingProfile / StyleProjection | Backend Style Engine | 请求任务投影 | 保存平行“文风记忆” |
| ProjectConstitution | Backend 项目配置领域 | 读取、提出修订、编译进 Prompt | 与 Harness System Prompt 混存 |
| AgentRun / RunEvent | Harness | 创建、恢复、取消、重试 | 让 Backend Domain 管聊天循环 |
| Tool/Skill 调度 | Harness | 发现、加载、权限检查 | Tool 直接访问 Repository |
| PromptCompiler / CachePlan | Harness | 确定性拼装请求 | 改写领域事实或权限 |
| UI Projection | Harness/Frontend | 展示运行状态和审批 | 前端自行推断正式状态 |

---

# 3. 依赖方向

唯一允许：

```text
Frontend
  ↓ Command / UI Projection
Harness / Application Orchestration
  ↓ Stable Backend Public Facades
Backend Application Services
  ↓
Domain + Repository + Search Infrastructure
```

禁止：

```text
Backend Domain → import Harness
Agent Model → SQLite / Repository
Tool → 内部数据库连接
Frontend → 直接调用模型并提交正式数据
Chapter Draft Model → 自行检索知识库
Prompt / Skill → 提升自身权限
Harness → 建立第二套 Subject/Memory/Plan/Style 表
```

---

# 4. 旧 Pipeline 的处理

`AgentRunEngine` 是新系统唯一长事务编排器，负责：

- 模型循环；
- Tool/Skill；
- Streaming；
- Retry/Cancel；
- Checkpoint；
- Approval wait；
- Recovery。

旧 `GenerationPipeline / AuditPipeline / RepairPipeline` 不得与它并列成为第二个总导演。仓库审计后只能选择：

```text
A. 拆成短事务 Backend Facade
B. 作为 Legacy Adapter 被 AgentRunEngine 调用
C. 被迁移替代后删除
```

禁止：

```text
AgentRunEngine
→ 旧 Pipeline 自己再跑一套模型、重试、Checkpoint、审批
```

---

# 5. Prompt 与领域数据边界

## 5.1 四种不同对象

```text
HarnessSystemPrompt
→ 通用 Agent 行为

ProjectConstitution
→ 小说最高提示词/项目创作宪法

WritingProfile + StyleProjection
→ 文风和表达

GenerationPackage
→ 当前章节任务
```

它们必须拥有不同 ID、Revision、存储位置和审批流程。

## 5.2 PromptCompiler 只负责拼装

标准顺序：

```text
Global Stable Prefix
→ Project Stable Prefix（含 ProjectConstitution）
→ Run-stable Task Block
→ Dynamic Context Suffix
→ Current Input
```

`AgentStateCapsule`、当前章节号、Run ID、最新工具结果和作者指令不得进入稳定前缀。

PromptCompiler 不得：

- 判断某条人物事实是否成立；
- 解决 CANON 冲突；
- 提取人物状态；
- 绕过 Context Compiler 选择正文证据；
- 通过 Prompt 文本改变 Permission Gateway。

---

# 6. 正式生成上下文的唯一入口

直接查询工具可用于回答、诊断和探索：

```text
subject.query
memory.query
plan.query
artifact.read
```

但任何资料要进入 Chapter Draft Model，必须经过：

```text
Agent 发现资料
→ ContextExtensionRequest / ManualPin
→ Backend compile_context(...)
→ View / Time / Authority / Revision 校验
→ 新 ContextProjection + ContextManifest
→ GenerationPackage
```

禁止 Agent 自己把查询结果列表拼进正式生成包。

---

# 7. 长篇正文装包契约

Backend Context Compiler 负责选择和验证，Harness 只负责将结果按 PromptCompiler 顺序放入请求。

```text
远处 → 摘要/事件索引
近期 → 高保真原文窗口
当前 → 选区/场景/章节全文
关键旧内容 → 精确原文证据
一致性 → Subject/View/Time 状态
文风 → StyleProjection 原文样本
```

Main Agent 和 Chapter Draft Model 使用不同 Projection。Harness 不得自行扩大最近章范围，也不得为了缓存把旧 ContextProjection 当成最新事实复用。

---

# 8. 知识库修改契约

## 8.1 统一流程

```text
Natural-language request
→ Agent proposal
→ Backend dry-run / validation
→ ApprovalRequest
→ deterministic commit
→ index/projection invalidation
→ audit artifact / undo
```

## 8.2 Subject 合并

模型可使用：

```text
subject.inspect
subject.compare
subject.propose_merge
subject.preview_merge
```

审批后，由应用服务调用：

```text
commit_subject_merge(request, approval, expected_revisions)
```

Backend 必须负责：

- 稳定主 SubjectId；
- alias/redirect/tombstone；
- 引用迁移；
- 字段冲突；
- MergeManifest；
- 索引刷新；
- Undo；
- Revision 并发控制。

Harness 只显示提案、审批和运行事件。

## 8.3 其他知识修改

知识、关系、状态、设定与计划统一转成 Backend 支持的候选或 ChangeSet。不存在专门的“Agent记忆数据库写工具”。

---

# 9. ProjectConstitution 契约

`ProjectConstitution` 建议作为后端项目配置领域的一等对象，因为它：

- 随项目导出、备份和迁移；
- 有 Revision 和作者审批；
- 被 Agent 与 Chapter Draft Model共同引用；
- 不属于 Harness 的通用系统规则；
- 不属于 Style Engine 的纯文风规则。

接口：

```text
get_project_constitution(project_id)
build_project_constitution_revision(source_decisions, base_revision)
commit_project_constitution_revision(proposal, approval, expected_revision)
```

Harness 负责：

- 从已确认讨论请求生成提案；
- 显示 Diff、来源和未纳入项；
- 等待审批；
- 将批准版本放入 Project Stable Prefix。

禁止：

- 从未经确认的聊天摘要直接覆盖；
- 将“没想好”补成规则；
- 用最高提示词改变数据库权限；
- 把它与 System Prompt 共用同一个 Revision。

---

# 10. 稳定 Public Facades

接线前至少冻结：

```text
compile_context
query_subject_evidence
query_plan
build_style_projection
get_project_constitution
build_project_constitution_revision
commit_project_constitution_revision
inspect_subjects
build_subject_merge
commit_subject_merge
audit_claims
build_changeset
commit_changeset
extract_state_candidates
submit_revision
```

Facade 返回 DTO，不暴露 ORM 实体、SQLite 游标或内部表结构。

---

# 11. 共享 DTO

```text
SubjectId
SubjectInspection
SubjectMergeProposal
MergePreview
MergeManifest
ProjectConstitutionRevision
ProjectConstitutionProposal
ProjectConstitutionProjection
ViewSpec
StoryTimeBoundary
NarrativeSequenceBoundary
AuthorityScope
ContextCompileRequest
ContextProjection
ContextManifest
EditorSnapshot
GenerationPackage
StyleProjection
AuditFinding
ChangeSet
ApprovalRequest
RevisionRef
EvidenceRef
```

任何字段不清楚时先提交 `DesignChangeProposal`，不得由 Agent 分支自行创造近义 DTO。

---

# 12. 实施顺序

## 可立即独立实现

```text
AgentRun / AgentRunEvent
EventStore
ModelAdapter / Streaming
UsageMeter
ArtifactStore
PromptComponent
PromptCompiler
CachePlan
ModelRequestManifest
Tool/Skill Catalog骨架
PermissionGateway骨架
UI Projections
```

## 必须等待后端 DTO/Facade 冻结

```text
context.compile 接线
Subject 查询与合并
Plan 查询
StyleProjection
AuditFinding
ChangeSet commit
状态提取与 STALE 传播
ProjectConstitution 持久化
Raw Reference 进入生成包
```

---

# 13. Codex 实施票据模板

```yaml
implementation_ticket:
  id: HARNESS-V1-A4
  objective: 实现 PromptCompiler 与 ModelRequestManifest
  design_sources:
    - Agent-Harness-v0.3 §15
    - 本契约 §5
  allowed_files: []
  backend_facades_used: []
  forbidden_changes:
    - 不新增人物/记忆/计划表
    - 不修改 Context Compiler 检索语义
    - 不让 Prompt 改变权限
  dto_dependencies: []
  migrations: []
  tests: []
  rollback_plan: ...
```

发现以下情况必须停止编码：

- 需要绕过现有 Facade 才能完成；
- 现有 Backend 与文档语义冲突；
- 需要建立第二套领域存储；
- 旧 Pipeline 和 AgentRunEngine 同时拥有编排权；
- DTO 尚未冻结；
- 需要迁移正式数据但票据没有迁移与回滚。

---

# 14. 强制回归门禁

## 数据与权限

- 模型不能直接写数据库；
- Subject 合并必须审批、可撤销；
- ProjectConstitution 修改不改变程序权限；
- CANON/PLAN 分离；
- Revision 冲突拒绝提交。

## 上下文

- Agent查询不能绕过 Context Compiler进入正文模型；
- 当前场景原文优先；
- 未来信息和错误 View 不进入 Projection；
- 摘要 STALE 后不可静默复用。

## 运行

- Cancel 后迟到事件不能复活 Run；
- 重启可恢复 WAITING_APPROVAL；
- Prompt 稳定前缀 Hash 可复现；
- Tool Schema 排序稳定；
- Backend Domain 不 import Harness。

---

# 15. 最终验收句

只有同时满足以下条件，才可以说“Agent 已接入后端”：

```text
Agent自然语言发起任务
→ Harness编排
→ Backend编译正式上下文
→ 模型生成候选
→ Backend审校原语
→ Agent解释与提案
→ 作者审批
→ Backend事务提交
→ 索引/投影更新
→ 重启后可恢复与审计
```

任何“Agent直接改卡片、直接改正文、直接拼上下文、直接写Prompt文件”的捷径，都不属于本设计。
