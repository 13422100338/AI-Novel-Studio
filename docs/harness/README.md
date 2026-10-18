# Harness 包(agent/ai-agent-v1 分支)

本目录承载《AI-Novel-Studio-Agent-Harness-总体设计 v0.3》与
《Agent实施与后端防冲突契约 v0.1》定义的 Agent Harness 实现。
开发在独立工作树 .codex/worktrees/ds-agent、分支 agent/ai-agent-v1 进行,
尚未集成 main;集成由作者协调。

## 所有权一句话

    Harness owns orchestration. Backend owns domain truth.
    PromptCompiler owns request assembly. Frontend owns presentation.

依赖方向唯一合法:Frontend -> Harness -> Backend Facades -> Domain + Storage。
tests/unit/harness/test_harness_boundaries.py 强制 domain/ 与 core/ 永不
import ai_novel_studio.harness。

## 模块索引

| 模块 | 设计来源 | 职责 |
| --- | --- | --- |
| run_state.py | §52、§63 | RunStage / RunEventType / HarnessRun / RunEvent |
| event_store.py | §52-§57 | 终态拒绝迟到事件、RUN_CREATED 独占、event_id 幂等 |
| event_repository.py | — | harness_runs / harness_run_events SQLite 持久化(schema v21) |
| model_roles.py | §35、§15.2、§66 | ModelRole / ModelRoleBinding / UsageMeasurement |
| model_adapter.py | §35 | 角色 -> TaskPurpose 路由,复用 LLMGateway/LLMContractRunner |
| usage_meter.py | §66 | 按角色拆账 UsageTracker,标注 ACCURATE/ESTIMATED/UNKNOWN |
| tool_registry.py | §29、§30 | ToolDefinition + 版本化目录 |
| permission_gateway.py | §31 | 确定性预执行检查,Prompt/Skill 不可绕过 |
| prompt_compiler.py | §15、§15.1、§15.2 | PromptComponent / CachePlan / ModelRequestManifest / 确定性装配 |
| artifacts.py | §20、§67 | 内容寻址 ArtifactStore(文件后端) |
| cancel_token.py | §54 | 单向取消 + cancel_run(与 EventStore/Gateway 联动) |
| skill_catalog.py | §32、§33 | Skill 目录与按需加载(无权限字段) |
| state_capsule.py | §14 | AgentStateCapsule 运行事实快照 |
| projections.py | §55、§64、§66 | RunStatus/Timeline/Usage/Recovery 投影 + recoverable_runs |
| approvals.py | 审计结论 2026-08-14 | ApprovalKind / ApprovalStatus / ApprovalRequest |
| approval_repository.py | — | harness_approvals 持久化(schema v22) |
| approval_service.py | §54-§57、§63 | 审批生命周期:请求/决议/WAITING_APPROVAL |
| proposals.py | §33、§38、§60 | PromptChange / SkillChange / Todo 提案记录 |
| completion_check.py | §57 | 程序侧完成校验(can_complete 门禁 + 事后审计) |
| conversation_summary.py | §17 | ConversationSummary / SummaryRevision 滚动摘要记录 |
| compaction.py | §18-§19 | 程序骨架提取 + 压缩禁区门禁 + 工件持久化 |
| failure_policy.py | §56 | 失败分类 -> RETRY/RECOMPILE_ONCE/SAVE_PARTIAL_AND_ASK/STOP |
| run_queue.py | §58 | V1 并发门禁:一个正式 Run 执行,其余排队 |

## 实施票

- A1 AgentRun + RunEvent + EventStore(schema v21,DCP-1 命名)
- A2 harness 包结构 + 模型角色绑定(DCP-2 包结构)
- A3 工具注册表 + 权限网关骨架
- A4 PromptCompiler + CachePlan + ModelRequestManifest
- A5 ArtifactStore + CancelToken + SkillCatalog
- A6 AgentStateCapsule + UI Projection 骨架
- A8a 审批生命周期骨架(schema v22)
- A9a 模型提案记录 + 程序侧完成校验
- A10a 会话滚动摘要 + 程序骨架提取 + 压缩门禁
- A9b 失败分类与重试决策
- A11a V1 并发队列门禁

## 集成状态

契约 §12"可立即独立实现"清单已全部完成。后端 H0 契约审计已被看板接受
(main @ 773c627),本分支已 rebase 到该基线。审计结论见
docs/harness/BACKEND_FREEZE_REQUEST.md:复用 R3a/ContextManifest v2/
StyleRetriever/AuditFinding/RevisionImpact 等现有能力,增量推进
R3b-Q1(query_subject_evidence)-> 运行时注入 -> R4(compile_context 门面)
-> 各 Facade 适配;ProjectConstitution / Subject Merge / ChangeSet / Plan
查询 / 状态提取先更新设计文档再实施。

审计确认:ApprovalRequest 生命周期归 Harness 所有,后端只验证审批凭证并
执行确定性提交——Harness 侧可在后端 DTO 冻结前先建审批生命周期骨架。

## 本地验证命令(工作树内)

    .venv/Scripts/python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage -q --basetemp .test-temp/pytest
    .venv/Scripts/python.exe -m ruff check src tests
    .venv/Scripts/python.exe -m mypy src/ai_novel_studio

注:--basetemp 是本地已知环境问题(P0-2)的文档化解法。

## 作者决策点

- DCP-1:HarnessRun/harness_runs 命名(避开 Phase-7 AgentRun/agent_runs)
- DCP-2:harness 独立包(契约 §3 依赖方向)
- Schema v21 合并顺序(main 现为 v20;后端新迁移将由主控分配 v22):
  A. 先合并 Harness v21 再开后端新迁移(推荐:纯追加,冲突面最小);
  B. Harness 分支 rebase 到后端新 v21 之后并改用 v22;
  C. 两者都不动,等下一个集成窗口一起排。
