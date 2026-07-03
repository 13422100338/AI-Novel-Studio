# AI Novel Studio Phase 5 正文生成流水线设计

## 状态

已由用户选择方案 A：先建立持久化状态机，再接入正式正文生成和 UI。

## 目标

阶段 5 把现有的“当前章要求、Brief 演示界面、统一模型网关、长篇记忆和动态上下文”连接成一条可恢复、可审查、不会静默覆盖正文的正式创作流水线。

首版开放基础模式和标准模式：

- 基础模式直接以当前章要求为最高优先级，不强制冻结 Brief；
- 标准模式必须使用人工冻结的 Chapter Brief；
- 严格模式保留入口但禁用，等待阶段 6 的独立审校与有界修复能力。

## 非目标

阶段 5 不实现以下功能：

- 自动接受正文、自动覆盖当前章节或自动连续生成整本书；
- 自动修复知识冲突、文风问题、误导线索或正典矛盾；
- 模型自动修改人物状态、正典、伏笔、文风规则或长期记忆；
- Agent 工具调用、并行写手、多模型循环评审或无限重试；
- 云同步、多人协作或远程项目数据库。

## 核心原则

1. 当前章要求始终是用户直接编辑的最高优先级章节指令。
2. 标准模式中，冻结 Brief 是导演模型到正文模型的唯一正式交接物。
3. 正文模型每次调用只负责生成正文，不同时生成摘要、记忆或审校报告。
4. 模型流式输出先写入生成检查点，不直接写入正式章节。
5. 用户明确“采用草稿”后，章节仓库才创建历史版本并替换正式正文。
6. 每次生成绑定 Brief、Context Manifest、模型配置、输出上限和来源修订。
7. 中断或失败必须保留已收到的正文，不自动发起新的付费调用。
8. 所有状态转换由确定性程序规则控制，不能由提示词决定。

## 总体架构

```text
Current Chapter Requirement
        |
        v
ChapterBriefCompiler -----> Brief sources and fingerprints
        |
        v
Draft Brief --human review--> Frozen Brief
        |                         |
        |                         v
        |                  ContextBuilder
        |                         |
        |                         v
Basic mode context       Context Manifest
        |                         |
        +------------+------------+
                     v
             ProseGenerationService
                     |
                     v
        Generation Run + append-only checkpoints
                     |
                     v
          Reviewable generated draft
                     |
             explicit user acceptance
                     v
             ChapterRepository.save_content
```

UI、应用服务、存储和模型调用保持分离：

- UI 只发出编译、冻结、克隆、开始生成、取消和采用草稿等意图；
- 应用服务验证状态、修订和权限，编排仓库与模型网关；
- 存储仓库负责事务、乐观修订、检查点和来源指纹；
- 模型网关只负责请求、流式事件、用量和供应商错误，不直接访问项目数据库。

## Schema v3

阶段 5 通过幂等迁移新增表，不修改或重建 Phase 1–4 表。

### chapter_requirements

每章保存一条当前有效要求：

```text
id, chapter_id, content, is_locked, revision, content_hash,
created_at, updated_at
```

`chapter_id` 唯一，确保每章只有一个当前要求。要求可直接人工编辑。锁定只阻止模型候选覆盖，不阻止用户明确解锁后修改。

### chapter_briefs

```text
id, chapter_id, mode, status, revision,
dramatic_purpose, target_length, story_date, pov_character_id,
hard_events_json, soft_goals_json, prohibited_changes_json,
creative_freedom_json, participants_json, knowledge_json,
clue_actions_json, style_rules_json, warnings_json,
source_fingerprint, content_hash, cloned_from_id,
created_at, updated_at, frozen_at
```

Brief 状态为：

- `DRAFT`：可编辑、可重新编译、不可用于标准模式生成；
- `FROZEN`：只读，可用于标准模式生成；
- `STALE`：来源变化后过期，不可生成；
- `ARCHIVED`：被新版本替代，仅供审计。

### brief_sources

```text
id, brief_id, source_type, source_id,
source_revision, source_hash, required
```

`(brief_id, source_type, source_id)` 唯一。来源包括当前章要求、章节正文、摘要、人物状态、知识记录、叙事线索、正典、文风规则和人工样章。指纹使用稳定排序后的来源类型、ID、修订号和哈希计算。

### generation_runs

```text
id, chapter_id, mode, status, brief_id, brief_revision,
context_manifest_id, model_provider_id, model_id,
output_token_limit, prompt_version, started_at, updated_at,
completed_at, accepted_at, failure_code, failure_message,
accepted_chapter_revision,
input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
```

生成状态为：

- `PREPARING`：验证来源并构建上下文；
- `READY`：上下文与 Manifest 已保存，尚未调用模型；
- `STREAMING`：正在接收正文；
- `PARTIAL`：收到部分正文后中断或用户取消；
- `COMPLETED`：模型正常结束，等待用户审查；
- `FAILED`：未收到正文即失败；
- `ACCEPTED`：用户已采用；
- `DISCARDED`：用户明确放弃，但记录仍保留。

同一章节同一时刻只允许一个 `PREPARING`、`READY` 或 `STREAMING` 任务。

### generation_checkpoints

```text
id, run_id, sequence, text_path, content_hash,
finish_reason, created_at
```

`(run_id, sequence)` 唯一。检查点只追加不覆盖。正文片段合并后原子写入 `.ai_pipeline/checkpoints/run_<UUID>/checkpoint_<sequence>.md`。数据库保存相对路径和哈希，不保存大段正文。

## Chapter Brief 编译

`ChapterBriefCompiler.compile(chapter_id, mode, expected_requirement_revision)` 返回草稿，不调用正文模型。

编译顺序：

1. 当前章要求；
2. 目标长度、视角人物、故事日期和戏剧功能；
3. 必须发生事件、软目标、禁止改动和创作自由；
4. 参与人物当前状态；
5. 人物知识与读者知识；
6. 活跃叙事线索及本章动作；
7. 正典和适用文风规则；
8. 近期全文、历史摘要和相关检索证据；
9. 冲突、过期来源、预算警告和省略项。

基础模式可跳过 Brief，但仍必须保存使用的当前章要求修订和 Context Manifest。标准模式只能使用 `FROZEN` 且来源指纹仍有效的 Brief。

## Brief 生命周期

### 冻结

冻结操作要求：

- 状态为 `DRAFT`；
- 调用者提供的 `expected_revision` 与数据库一致；
- 当前来源指纹与草稿指纹一致；
- 没有未解决的必需来源缺失或知识冲突；
- 至少包含一个当前章要求和一个必须事件或明确的戏剧功能。

冻结后内容不可修改。任何编辑都必须克隆为新草稿。

### 失效

当前章要求、来源章节、摘要、人物状态、知识、线索、正典或文风规则的修订/哈希变化，会把依赖 Brief 标记为 `STALE`。失效只改变状态，不删除 Brief 或来源快照。

### 克隆

用户可以把 `FROZEN` 或 `STALE` Brief 克隆为新 `DRAFT`。克隆保留原内容和 `cloned_from_id`，重新读取当前来源，生成来源差异：新增、删除、修订变化和哈希变化。用户审查后才能再次冻结。

## ContextBuilder 接入

阶段 4 的 `ContextBuilder` 继续负责整块预算选择。阶段 5 新增适配层，把 Brief 与仓库数据转换为 `ContextBlock`：

1. 系统写作边界与用户当前章要求：必需；
2. 冻结 Brief：标准模式必需；
3. 近期章节全文：高优先级；
4. 当前人物状态和知识边界：高优先级；
5. 活跃线索、正典和文风规则：高优先级；
6. 较早章节摘要和 FTS 证据：可使用摘要回退；
7. 卷/全书摘要：较低优先级。

所有块必须携带来源 ID、修订、哈希和选择理由。超出预算时只允许整块回退或省略，不能从正文中间截断。生成开始前必须持久化 Context Manifest。

## 正文模型输入顺序

模型消息保持稳定前缀优先，以提高兼容供应商的提示缓存命中概率：

1. `system`：正文写手职责、不得输出解释/分析、不得修改正典、不得调用工具；
2. `system`：输出格式和中断规则；
3. `user`：当前章要求；
4. `user`：冻结 Brief（标准模式）或基础模式约束；
5. `user`：近期章节全文；
6. `user`：人物、知识、线索、正典和文风上下文；
7. `user`：历史摘要与检索证据；
8. `user`：最终任务，要求只输出本章正文。

模型输出 Token 上限使用用户设置值。若超过已知模型能力，生成前明确报错，不静默缩减。

## 生成状态机

`ProseGenerationService.prepare(request)` 完成所有不产生费用的验证和上下文构建，并把任务推进到 `READY`。只有 `start_stream(run_id)` 才调用模型。

流式事件处理：

- `TEXT`：追加到内存缓冲，并按字符阈值或时间阈值保存检查点；
- `REASONING`：只进入可选诊断/用量记录，不混入正文；
- `USAGE`：更新 Token 用量；
- `COMPLETED`：保存最终检查点并标记 `COMPLETED`；
- `PARTIAL_FAILURE`：有正文则标记 `PARTIAL`，无正文则标记 `FAILED`。

用户取消时不发起第二次请求。已经收到正文则保存为 `PARTIAL`；尚未收到正文则标记 `FAILED`，错误码为 `USER_CANCELLED`。

阶段 5 不支持从供应商流的中间位置继续同一次请求。“恢复”表示读取已保存草稿并允许用户采用、丢弃或明确重新生成；重新生成会创建新的 run ID 和新的计费调用。

## 采用草稿

`GenerationAcceptanceService.accept(run_id, expected_chapter_revision)` 只接受 `COMPLETED` 或用户明确选择的 `PARTIAL` 草稿。

采用操作在一个受控流程中执行：

1. 校验 run 尚未采用或丢弃；
2. 校验章节修订号未变化；
3. 校验检查点文件哈希；
4. 使用 `ChapterRepository.save_content` 创建旧正文快照并写入新正文；
5. 把 run 标记为 `ACCEPTED` 并记录新章节修订；
6. 触发阶段 4 的记忆依赖失效；
7. 生成摘要/人物/伏笔候选仍是后续独立调用，不在采用事务中自动执行。

如果正文保存成功但 run 状态更新失败，恢复服务通过章节版本和内容哈希识别该状态并提示人工确认，不能再次自动覆盖正文。

## UI 行为

### Brief 审查页

现有演示页改为服务驱动：

- 展示 Brief 状态、修订、来源指纹、来源徽章和过期差异；
- 草稿可编辑；冻结 Brief 只读；
- “冻结”需要明确点击；
- “克隆为新草稿”不会改变旧 Brief；
- 冲突和缺失来源阻止冻结并显示具体记录。

### 正文面板

- 模式选择提供基础、标准、严格；严格模式禁用并说明阶段边界；
- 标准模式未冻结 Brief 时，“生成正文”不可用；
- 点击生成先显示上下文预算与 Manifest 摘要，再由用户确认付费调用；
- 流式正文显示在独立草稿区，不覆盖可编辑的正式正文；
- 生成期间提供取消；完成后提供采用、放弃和重新生成；
- Token 用量区区分实际、估算、缓存和推理 Token；
- 重启后发现未结束 run 时，显示恢复入口。

## 错误处理

- Brief 过期：阻止标准模式生成，提供来源差异和克隆入口；
- 必需上下文超预算：在调用模型前失败，列出超限块；
- 模型输出上限不支持：显示用户值和模型值，不修改设置；
- API 调用前失败：run 标记 `FAILED`，不产生正文检查点；
- 流式中断：保留已接收正文并标记 `PARTIAL`；
- 检查点写入失败：停止流消费并保留上一个有效检查点；
- 章节被并发修改：拒绝采用，保留生成草稿；
- Manifest、Brief 或检查点哈希不一致：阻止生成/采用并要求完整性检查；
- 程序退出：启动时扫描非终态 run，绝不自动重发请求。

错误消息不得包含 API Key、完整供应商响应体或本机私人路径。

## 测试标准

阶段 5 至少覆盖：

- schema v3 从旧项目迁移、幂等性和数据保留；
- 当前章要求锁定、乐观修订和模型不可覆盖；
- Brief 编译来源顺序、指纹稳定性、冻结、失效、克隆和差异；
- 基础模式无需 Brief，标准模式必须使用有效冻结 Brief；
- Context Manifest 与 run、Brief、章节来源互相可追踪；
- 用户输出 Token 上限原样传递和模型能力溢出报错；
- 同章单写手约束和非法状态转换拒绝；
- 流式文本顺序、reasoning 隔离、检查点追加、部分失败和取消；
- 正式正文在采用前保持不变；
- 采用时生成章节历史、并发修订拒绝和记忆依赖失效；
- 重启恢复不会自动重新调用模型；
- UI 的模式、冻结、生成、取消、采用和恢复状态；
- 100+ 章项目下的上下文准备与检查点压力测试；
- 全量 pytest、Ruff、mypy、源码/历史/dist 隐私扫描、Windows 构建和 EXE 启动探针。

## 实施顺序

1. schema v3 与领域状态；
2. 当前章要求持久化；
3. Brief 仓库、来源指纹和生命周期；
4. ChapterBriefCompiler 与冲突验证；
5. ContextBlock 适配与生成准备；
6. generation run、检查点和单写手约束；
7. 正文流式模型服务；
8. 草稿采用与恢复；
9. Brief/正文 UI 接入；
10. 压力测试、文档、Windows 构建和桌面同步。
