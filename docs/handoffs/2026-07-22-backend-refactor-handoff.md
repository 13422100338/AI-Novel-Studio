# AI Novel Studio 后端重构交接说明

> 状态快照：2026-07-22<br>
> 项目目录：`C:\Users\钟子诚\Desktop\AI-Novel-Studio`<br>
> 后端方案：`C:\Users\钟子诚\Downloads\AI_Novel_Studio_后端改进方案_Subject_View_Time_Context_Compiler_修订版.md`

## 1. 当前 Git 状态

- 当前分支：`main`
- 当前提交：`e35b50df0536cf220d8cd049e1b86766e20b8046`
- `main` 与 `origin/main` 完全一致
- 生成本交接说明前，工作区干净
- 原分支 `codex/backend-phase-3-context-compiler` 当前已不在远程，但其提交已经包含在 `main`
- 同一提交上次完整验证结果：
  - Pytest：`532 passed`
  - Ruff：通过
  - MyPy：通过，检查 173 个源码文件
- 整理本交接说明时未重新运行全量测试

## 2. 必须遵守的架构原则

这是现有 V3 后端的渐进升级，不是重新创建第二套后端。

必须继续保留和扩展：

- Project、Chapter、Markdown 正文与 SQLite
- 现有 Repository
- LLM Gateway 与 Provider Adapter
- Generation Pipeline、Checkpoint、Recovery、Brief、GenerationRun
- 现有 Character Identity，作为 Subject Registry 的基础
- 现有 Context Builder，逐步演进为 Context Compiler 2.0
- 现有 History Retriever，扩展为 Hybrid Retrieval
- 现有 Style Retriever，扩展 Style Exemplar Retrieval
- Character Timeline，作为 State Events/Snapshot 基础
- Canon Ledger，作为 Canon Facts 基础
- 现有 Audit Pipeline，扩展新的检查器

禁止：

- 新建第二套 Subject/人物身份系统
- 新建第二条 Context 主链
- 新建第二套 Repository、Retriever、人物状态或正典真相源
- 使用 LLM 自动重新解释旧事实
- 让模型候选未经用户审查直接成为正式记忆
- 把 Embedding 缓存变成故事真相源
- 恢复已经删除的“严格模式”作为用户生成模式

## 3. 已完成内容

### 3.1 Phase 0：边界与 Baseline

- 权威源与派生层边界已经记录
- 建立 10 个确定性章节上下文任务
- Baseline 已演进至 v6
- 指标已覆盖召回、精度、禁用信息、Token 和编译耗时
- 数据库迁移已拆分为独立模块并验证原子回滚

### 3.2 Phase 1：Subject Registry

- Schema v12：`subjects`、`subject_aliases`
- 现有人物 ID 直接作为稳定 Subject ID
- Character Identity 已收敛到 Subject Registry
- 人物创建、别名、合并和 Undo 保持事务一致
- Agent 只能提出待审查合并建议，不能直接修改身份

### 3.3 Phase 2：View Assertions

- Schema v13-v15：`view_assertions`
- 已支持：
  - `WORLD_TRUTH`
  - `CHARACTER_VIEW`
  - `READER_VIEW`
  - `AUTHOR_PLAN`
- 已实现双时间区间、审批状态、来源修订失效
- 身份合并及 Undo 可以迁移/恢复相关 View 引用
- 已支持将经过确认的旧 Reader Knowledge 转换为 Reader View
- Reader/POV View 已进入正文生成上下文

### 3.4 Phase 3：Context Compiler 已完成部分

- 确定性 Hard Filter
- View、时间、修订、权限、冲突和失效过滤框架
- Task-aware 词法重排
- 精确内容去重
- Canon 冲突禁止进入 Writer
- 最近正文最低覆盖保证
- 动态 Token 预算、完整 fallback 和省略原因
- Context Manifest 已能记录选入、排除、fallback 和警告
- History Retriever 已扩展：
  - 精确短语召回
  - FTS5 Keyword/BM25 召回
  - Subject 召回
  - 可选 Embedding 召回接口
- Schema v16：`memory_embeddings`
- Embedding 缓存持久化、来源哈希、失效、余弦召回和重建扫描
- `EmbeddingIndexService` 已实现批量索引编排、维度校验和逐项失败恢复

## 4. 尚未完成：最高优先级

### 4.1 Embedding 尚未真正接入生产主链

现状：

- Embedding Protocol、SQLite 缓存、索引服务和查询召回已经完成
- 没有真实 Provider Adapter
- 生产环境没有构造 `StoredEmbeddingRecallProvider`
- 正文生成仍主要使用词法和 Subject 路线
- 没有后台或手动索引入口

下一张独立开发票建议是：

> 将现有 Embedding 边界接入真实 Provider 和生产 HistoryRetriever，同时确保失败时自动退回词法与 Subject 召回。

需要覆盖：

- 在现有 LLM Provider/配置体系中声明 Embedding 能力
- 文档与查询使用同一 `model_id` 和维度
- 调用现有 `EmbeddingIndexService` 建立缺失或过期索引
- 在现有 HistoryRetriever 中注入 `StoredEmbeddingRecallProvider`
- Provider 不支持、超时、限流、响应损坏时安全降级
- 不记录 API Key、正文或原始模型响应
- 测试重启后缓存复用、模型切换、来源更新和失败重试

关键文件：

- `src/ai_novel_studio/application/embedding_index_service.py`
- `src/ai_novel_studio/core/context/history_retriever.py`
- `src/ai_novel_studio/infrastructure/storage/search_repository.py`
- `src/ai_novel_studio/infrastructure/llm/gateway.py`
- `src/ai_novel_studio/infrastructure/llm/provider_adapter.py`
- 项目运行时的依赖装配位置

### 4.2 Context Manifest 还不是完整的 Manifest 2.0

当前 Manifest 缺少或不够明确：

- Manifest/schema 版本
- 目标章节基础修订
- Context Compiler 版本
- Subject ID
- View 类型
- Story/Narrative 时间范围
- Authority/Review 状态
- 召回路线
- BM25、Embedding、任务重排等分项分数
- 冲突与依赖的结构化信息
- 为什么被截断或使用 fallback 的完整结构

升级时必须保持旧 JSON Manifest 可读取，不能直接破坏历史 GenerationRun。

### 4.3 Time Filter 和 Eligibility 尚未覆盖所有候选来源

目前双时间过滤主要落实在 `view_assertions`。

其他 Character State、Canon、Clue、Style 和历史记忆仍有不少过滤发生在各自 Provider/Repository 内部，并默认生成“允许”的 ContextBlock。这会导致：

- Manifest 看不到上游为什么没召回某条记录
- 不同候选来源的时间规则不完全统一
- 后续 State Events 接入时容易形成两套过滤逻辑

应逐步把权威来源的时间、修订、权限和冲突决策映射为统一 `ContextEligibility`，但不要把所有数据复制进一张新表。

### 4.4 当前 Rerank 仍是第一版

已实现的是确定性词法重排，不是完整的语义重排。

Embedding 接入后需要：

- 合并 BM25、Embedding、Subject、Pin、Recency 和 Staleness 信号
- 记录每条候选由哪些路线召回
- 用 Baseline 校准权重
- 没有评估证据前，不要加入任意相似度阈值或复杂权重

### 4.5 Context Projection 仍有缺口

当前做法正确地禁止 `WORLD_TRUTH` 和 `AUTHOR_PLAN` 自动暴露给 Writer，但尚未实现：

- 将隐藏原因转换为“不泄密的行为约束”
- 更丰富的 POV Knowledge/Reader Knowledge 投影
- Subject x View x Time 的明确分区输出

必须避免把隐藏真相原文发给 Writer。只有存在明确、经过审查的投影规则时，才能生成非泄密行为约束。

## 5. Phase 2 后续改进

- Legacy Reader View 转换目前主要是服务 API，缺少完整 UI 操作入口
- View Assertion 的批量模型提取、编辑和冲突处理仍未完成
- 非人物 Subject 类型尚未实现：
  - LOCATION
  - ORGANIZATION
  - ITEM
  - ABILITY
  - EVENT
  - CONCEPT
- 不应一次性添加全部类型，应按实际检索需求逐类增加
- 近似重复人物或信息不能由模型自动合并，仍需走人工审查流程

## 6. 严格模式的遗留清理

用户层只允许：

- `BASIC/快速`
- `STANDARD/普通`

代码中仍保留 `CreationMode.STRICT`，但目前只是“普通模式 + 生成前审校”的历史持久化编码，不是第三个 UI 模式。

后续应单独设计兼容迁移：

- 将 Generation Profile 与 Audit Policy 分离
- 新运行不再创建 `STRICT` 生成模式
- 旧数据库中的 `STRICT` 仍可读取
- 不要直接删除旧枚举或旧数据库值
- 建议最终形式：
  - `GenerationProfile.QUICK/NORMAL`
  - `AuditPolicy.MINIMAL/STANDARD/DEEP`

## 7. Phase 4-7 尚未完成

### 7.1 Phase 4：State Events + Snapshot

- 基于现有 Character Timeline 扩展
- 优先支持心理、动机、目标、关系、位置、伤势
- Snapshot 必须是事件派生缓存，不能成为第二真相源
- 不做完整 World Engine

### 7.2 Phase 5：Style Engine

- 扩展现有 Style Retriever
- Style Profile、分层规则、正文 Exemplar Retrieval
- Lightweight Style Drift Audit
- 不建立第二套风格系统

### 7.3 Phase 6：Evidence Audit + Deep Audit

现有 Audit Pipeline、持久化和恢复继续保留，新增：

- Knowledge Boundary
- Timeline
- Character Consistency
- Intent Miss
- Style Drift

每条问题必须带证据。深度审校是生成后的独立动作，不是第三种生成模式。

### 7.4 Phase 7：正式 Evaluation Harness

现有 Baseline 只有确定性上下文任务，仍缺：

- 真实 Provider Token 和延迟
- 生成失败率
- 草稿采纳率
- 人工修改距离
- 人工修改时间
- Style Drift 回归
- Human Revision Cost Tracking

这些指标应做成用户主动启用的本地观测，不能上传小说正文。

## 8. 当前可接受但需监控的技术限制

- Embedding 以 JSON 向量存入 SQLite
- 余弦召回是受限线性扫描
- 上限为 5000 行及约 800 万个向量值
- 这是可移植的阶段性实现
- 在真实百万字项目证明性能不足前，不要贸然引入第二个向量数据库

## 9. 推荐下一步

只处理一个独立任务：

> 完成真实 Embedding Provider、索引入口和生产 HistoryRetriever 注入，并实现失败时无感降级到现有词法/Subject 召回。

开始前先：

1. 确认 `main`、工作区和 HEAD。
2. 从 `main` 创建新的 `codex/` 功能分支。
3. 阅读 ADR 0020、0021 和现有测试。
4. 不改数据库真相源，不新建第二条 Retriever。
5. 完成后运行全量 Pytest、Ruff、MyPy，并创建独立检查点提交。
