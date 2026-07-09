# AI Novel Studio Phase 6 审校与修复系统设计

## 状态

已由用户认可方向：阶段 6 不做完整 Agent 工具循环，优先建立“审校、定位、局部修复、人工确认”的可靠管线。

实现状态：已落地为 `0.6.0`。当前实现包含审校 schema v4、审校仓库、确定性审校落库、模型审校结果验证落库、有界修复 proposal、人工应用修复、provenance 记录、严格模式采用拦截，以及 UI 中的确定性审校入口。完整 Agent 工具调用仍保留为后续阶段。

## 背景

阶段 5 已经把当前章要求、冻结 Brief、动态上下文、正文生成、草稿检查点和人工采用连接成正式创作流水线。正文模型的职责被限制为“生成当前章草稿”，不会直接写入正式正文。

阶段 6 在此基础上增加独立的质检层。它负责发现问题、解释证据、提出局部修复建议，并把是否应用修改的最终权力保留给用户。

阶段 6 的核心判断是：长篇小说里的矛盾不一定都是错误，也可能是伏笔、误导、角色认知差或叙事策略。因此模型不能自动覆盖正文、人物状态、伏笔账本或正典记录。

## 目标

- 对生成草稿或正式章节运行审校。
- 发现当前章要求遗漏、人物状态冲突、伏笔遗忘、正典矛盾、时间线问题、知识边界泄漏和文风漂移。
- 将确定性规则检查和模型语义审校分开。
- 将审校、修复、记忆抽取、正文生成分开。
- 所有模型结构化输出在保存前必须验证。
- 修复建议默认只生成局部替换或补写方案，不能直接覆盖正式正文。
- 用户可以接受、拒绝、标记误报或转为正典说明。
- 为严格模式和后续 Agent 工具调用打基础。

## 非目标

阶段 6 不实现以下能力：

- 模型自动循环审校并改完整章。
- 模型自动覆盖正式正文。
- 模型自动修改人物状态库、伏笔账本、正典规则或长期记忆。
- 一次模型调用同时完成审校、修复、摘要、人物提取和记忆更新。
- 模型在推理中主动调用记忆库工具。
- 对百万字全文做一次性全量审校。
- 云端协作、多用户审校或远程项目数据库。

完整 Agent 工具调用留到阶段 7 之后处理。

## 核心原则

1. 审校结果是建议，不是事实。
2. 正式正文只有用户确认后才能修改。
3. 确定性规则优先于提示词约束。
4. 模型输出必须按 schema 验证后才保存。
5. 修复建议必须绑定正文修订号和原文片段。
6. 如果正文在修复建议生成后发生变化，旧修复建议不能直接应用。
7. 伏笔、误导和角色认知差不能被简单当成错误自动修掉。
8. 审校、修复、正文生成、记忆抽取分别由不同服务负责。
9. UI 只发出用户意图，不直接操作 SQLite 或模型网关。
10. 所有被接受的修复都要留下来源记录。

## 总体流程

```text
Generated Draft / Formal Chapter
        |
        v
DeterministicAuditService
        |
        v
ModelAuditService
        |
        v
Audit Findings
        |
        v
RepairProposalService
        |
        v
Validated Patch / Replacement
        |
        v
Human Review
        |
        +---- reject / false positive / convert to canon note
        |
        v
Apply accepted repair
        |
        v
Provenance record + chapter revision
```

阶段 6 插入在阶段 5 的“草稿生成完成”和“用户采用正文”之间，也可以用于已经存在的正式章节。

## 领域模型

### audit_runs

记录一次审校任务。

```text
id
chapter_id
target_kind             -- GENERATED_DRAFT / FORMAL_CHAPTER
target_id               -- generation_run_id 或 chapter_id
target_revision
target_hash
mode                    -- BASIC / STANDARD / STRICT
status                  -- PREPARING / RULE_CHECKED / MODEL_CHECKED / COMPLETED / FAILED
model_provider_id
model_id
prompt_version
started_at
completed_at
failure_code
failure_message
input_tokens
output_tokens
cached_input_tokens
reasoning_tokens
```

### audit_findings

记录一个审校问题。

```text
id
run_id
category                -- STYLE / REQUIREMENT / CHARACTER / KNOWLEDGE / CLUE / CANON / TIMELINE / FORMAT
severity                -- INFO / WARNING / ERROR / BLOCKER
source                  -- DETERMINISTIC / MODEL
location_json
evidence
explanation
related_source_json
confidence
status                  -- OPEN / ACCEPTED_REPAIR / REJECTED / FALSE_POSITIVE / CONVERTED_TO_CANON
created_at
updated_at
```

### repair_proposals

记录一个局部修复建议。

```text
id
finding_id
target_revision
target_hash
strategy                -- REPLACE_TEXT / INSERT_TEXT / DELETE_TEXT / NOTE_ONLY
target_text
replacement_text
patch_json
explanation
risk_note
status                  -- DRAFT / VALIDATED / APPLIED / REJECTED / STALE / INVALID
created_at
applied_at
```

### provenance_events

记录被接受的修复来源。

```text
id
chapter_id
chapter_revision_before
chapter_revision_after
event_type              -- REPAIR_APPLIED / FINDING_REJECTED / FALSE_POSITIVE / CANON_NOTE_CREATED
source_audit_run_id
source_finding_id
source_repair_id
summary
created_at
```

## 审校类型

### 当前章要求审校

检查正文是否完成当前章要求中的硬性事项。

典型问题：

- 必须发生的事件没有出现。
- 禁止改动被违反。
- 视角人物不一致。
- 章节目标和正文重点错位。

### 人物一致性审校

检查人物状态、心理、动机、关系和行动是否冲突。

典型问题：

- 角色上一章已经知道某信息，本章却像完全不知情。
- 角色死亡、失踪、重伤后无解释正常行动。
- 人物称呼、关系、能力边界突然变化。

### 知识边界审校

检查角色知道了不该知道的信息，或叙述把读者知识错误塞给人物。

典型问题：

- 反派秘密被主角无来源知道。
- 角色引用了尚未发生或尚未公开的信息。
- 旁白误把读者视角当成角色视角。

### 伏笔与正典审校

检查活跃伏笔、世界规则、重要事实是否被破坏。

典型问题：

- 已锁定世界规则被正文违背。
- 伏笔承诺被遗忘。
- 误导线索被正文提前解释穿。
- 模型把“故意矛盾”当作普通错误。

### 时间线审校

检查章节顺序、日期、年龄、旅行时间和事件先后。

典型问题：

- 两地瞬移没有解释。
- 一天内发生过多不可能事件。
- 已经过去的事件被当成未来事件。

### 文风审校

检查风格漂移和 AI 输出痕迹。

典型问题：

- 正文突然变成提纲、总结、说明文。
- 对话标签重复。
- 句式过度机械。
- 出现“当然可以”“下面是正文”等模型残留。

### 格式审校

检查机械格式问题。

典型问题：

- 标点未闭合。
- 章节标题异常。
- 重复段落。
- 空行异常。
- 正文过短。

## 确定性审校服务

`DeterministicAuditService` 不调用模型，只做稳定规则检查。

建议第一版规则：

- 空正文检查。
- 章节标题检查。
- 模型残留语检查。
- 重复段落检查。
- 基础标点闭合检查。
- 当前章要求为空检查。
- 正文长度明显低于期望检查。
- 当前章要求关键词粗匹配检查。

确定性审校输出 `audit_findings`，`source = DETERMINISTIC`。

## 模型语义审校服务

`ModelAuditService` 调用模型，但只允许输出结构化审校结果。

### 输入顺序

```text
system: 审校员职责、不可改正文、不可改记忆、只输出 JSON
system: 输出 schema 和严重程度定义
user: 审校任务类型
user: 当前章要求
user: 目标正文或生成草稿
user: 冻结 Brief 摘要
user: 相关人物状态
user: 相关知识边界
user: 活跃伏笔、正典规则、时间线记录
user: 最近章节摘要或必要原文
user: 确定性审校发现
user: 最终要求，只返回审校 findings
```

### 输出约束

模型必须输出 JSON，格式类似：

```json
{
  "findings": [
    {
      "category": "CHARACTER",
      "severity": "WARNING",
      "location": {
        "quote": "原文片段",
        "approximate_position": "middle"
      },
      "evidence": "为什么认为有问题",
      "explanation": "问题说明",
      "related_sources": [
        {
          "type": "character_state",
          "id": "character-id"
        }
      ],
      "confidence": 0.72
    }
  ]
}
```

程序必须验证：

- JSON 可解析。
- `category` 和 `severity` 在允许枚举内。
- `confidence` 是 0 到 1 之间的数字。
- `quote` 如果存在，必须能在目标正文中找到，或标记为弱定位。
- 单次 findings 数量不能超过上限。
- explanation、evidence 不得为空。

验证失败时，审校任务失败或进入“需要人工查看原始输出”的状态，不保存为正式 findings。

## 修复建议服务

`RepairProposalService` 只针对一个 finding 或一小组强相关 findings 生成局部修复。

### 输入顺序

```text
system: 修复员职责、只做局部修复、不得改正典、不得重写整章
user: 问题 finding
user: 相关正文片段
user: 当前章要求
user: 必须遵守的人物、伏笔、正典、知识边界
user: 输出 schema
```

### 输出约束

模型输出类似：

```json
{
  "strategy": "REPLACE_TEXT",
  "target_text": "需要替换的原文",
  "replacement_text": "建议替换后的文本",
  "explanation": "这样修改的理由",
  "risk_note": "可能影响的伏笔或人物状态"
}
```

程序必须验证：

- `target_text` 存在于目标正文。
- 当前正文 revision 和 `target_revision` 一致。
- 替换范围没有超过单次修复上限。
- 不修改锁定正典、锁定人物状态或锁定伏笔。
- `replacement_text` 不为空。
- 修复后不会产生空章节。

验证通过后，proposal 状态为 `VALIDATED`。只有用户点击接受后，才能应用。

## 严格模式

阶段 6 完成后，严格模式可以开放。

严格模式定义：

```text
生成草稿
  -> 自动运行确定性审校
  -> 自动运行必要的模型审校
  -> 如果存在 ERROR 或 BLOCKER，草稿进入待修复状态
  -> 用户审阅后才能采用为正式正文
```

严格模式不等于自动改稿。它只是在正式采用前强制审校。

## UI 设计

新增“审校与修复”工作区。

推荐布局：

```text
左侧：问题列表
中间：正文定位与证据
右侧：修复建议 / diff 对比
```

### 左侧问题列表

支持筛选：

- 全部
- 当前章要求
- 人物
- 知识边界
- 伏笔
- 正典
- 时间线
- 文风
- 格式

每个问题显示：

- 严重程度
- 类型
- 来源
- 置信度
- 状态

### 中间证据区

显示：

- 问题说明
- 相关正文片段
- 相关人物状态、伏笔或正典来源
- 模型解释
- 确定性规则命中原因

### 右侧修复区

显示：

- 修复策略
- 原文
- 建议文本
- diff 对比
- 风险提示
- 接受 / 拒绝 / 标记误报 / 转为正典说明

## 和现有模块的边界

- UI 层：只负责展示审校结果和发送用户操作。
- Pipeline 层：负责编排审校与修复流程。
- Data 层：保存 audit run、finding、proposal 和 provenance。
- Model Gateway：只负责模型请求和 token 用量，不访问项目数据库。
- Memory 层：只提供审校所需的相关状态，不被审校模型直接修改。
- Chapter Repository：只在用户接受修复后保存正文新版本。

## 错误处理

- 目标正文为空：审校失败，显示明确提示。
- 目标正文 revision 变化：修复建议标记为 `STALE`。
- 模型输出非法 JSON：不保存 findings，保留诊断信息。
- 修复 target_text 找不到：proposal 标记为 `INVALID`。
- 模型请求失败：audit run 或 proposal 标记为 `FAILED`。
- 发现 BLOCKER：严格模式下阻止采用草稿，普通模式下只提示。
- 写入 provenance 失败：正文修改不得静默完成，需要回滚或报告人工处理。

错误消息不得包含 API Key、完整供应商响应体、用户真实姓名或本机隐私路径。

## 测试标准

阶段 6 至少覆盖：

- schema 迁移幂等性。
- audit run 状态转换。
- 确定性规则输出稳定 findings。
- 模型非法 JSON 被拒绝。
- findings 枚举校验。
- 修复 proposal 的 revision guard。
- target_text 不存在时不能应用。
- 正文变化后旧 proposal 变为 stale。
- 接受修复会创建章节历史版本。
- 接受修复会写入 provenance event。
- 标记误报后不会阻止严格模式。
- BLOCKER 在严格模式下阻止草稿采用。
- 普通模式下审校 findings 不会自动修改正文。
- 100+ 章项目下只加载相关上下文，不扫描全文正文。

## 实施顺序

1. 新增审校领域模型、枚举和 schema 迁移。
2. 新增 `DeterministicAuditService`，先实现基础格式和机械规则。
3. 新增 `ModelAuditService`，实现结构化 JSON 协议和验证。
4. 新增 `RepairProposalService`，实现局部修复建议和 revision guard。
5. 新增应用修复服务，复用章节历史和正式正文保存边界。
6. 新增审校与修复 UI 工作区。
7. 将严格模式从占位状态接入审校流程。
8. 补充测试、文档、构建验证和桌面同步。

## 验收标准

阶段 6 完成时，应满足：

- 用户可以对当前章节或生成草稿运行审校。
- 审校结果以分类问题列表展示。
- 用户可以针对单个问题生成局部修复建议。
- 用户可以接受、拒绝或标记误报。
- 接受修复后正文产生新版本并保留来源记录。
- 模型输出异常不会污染项目数据。
- 严格模式可阻止明显有严重问题的草稿被直接采用。
- 现有阶段 5 正文生成流程不被破坏。
