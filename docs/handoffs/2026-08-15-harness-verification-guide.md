# AI Novel Studio — Harness 可运行性检查指导(给第三方模型)

> 日期:2026-08-15 · 目的:让另一个模型独立检查 Harness 是否真的能运行
> 分支:`agent/ai-agent-v1`(工作树 `<repo>/`)
> 状态:B1–B10 共 9 个提交已在分支上,未合并 main;harness+storage 422 测试通过,ruff/mypy 0

## 1. 一句话背景

Harness 是新的编排层(Agent Run 生命周期),后端 Domain Kernel 是领域真相
唯一权威。两者唯一合法依赖方向:Harness → Backend Facade,严禁反向。
检查目标:确认这套东西能组装起来跑通"编译→生成→审校→审批→提交"链路,
以及事件日志/恢复投影在重启后成立。

## 2. 代码路径与大致结构

Harness 主体:`src/ai_novel_studio/harness/`,按职责分:

| 文件 | 大致职责 |
|---|---|
| `run_engine.py` | 唯一长事务编排器:队列门禁、阶段迁移、取消令牌、审批/编译/正文流端口 |
| `agent_loop.py` | B8 组装链(参考实现):compile→package→stream→audit→changeset→approval,`ChapterGenerationLoop` |
| `compile_step.py` | 后端 CompileContextService 的端口适配器 |
| `draft_stream.py` | 正文候选流:流式事件、检查点、残稿/候选稿工件 |
| `approval_resolver.py` | 批准后派发后端 commit 门面(ChangeSet/SubjectMerge) |
| `subject_tools.py` / `core_tools.py` | Agent 工具:subject 四件套与 9 个核心工具(薄门面,零新依赖) |
| `prompt_compiler.py` | 确定性请求拼装(稳定前缀/动态后缀)+ ModelRequestManifest |
| `event_store.py` / `event_repository.py` / `run_state.py` | 事件日志、run 状态机、事件词汇 |
| `approvals.py` / `approval_service.py` / `approval_repository.py` | 审批生命周期 |
| `projections.py` / `state_capsule.py` | 只读投影(状态/时间线/恢复/上下文状态栏)与胶囊 |
| `artifacts.py` / `retention.py` | 内容寻址工件存储与保留清理 |
| `skill_catalog.py` / `skill_runtime.py` | Skill 目录与按需装载 |
| `model_adapter.py` / `model_roles.py` / `usage_meter.py` | 模型角色绑定、流式适配、用量 |
| 其余 | 取消令牌、并发队列、完成校验、失败分类、会话压缩、宪法流、权限网关、工具注册表 |

后端被调用的门面(只读依赖,不改):
`application/compile_context_service.py`、`audit_claim_service.py`、
`changeset_service.py`、`subject_merge_service.py`、
`subject_inspection_service.py`、`plan_query_service.py`、
`project_constitution_service.py` 等。

Schema:最新 v24(`infrastructure/storage/schema_migrations_v24.py` 为
harness_model_request_manifests 表;v21/v22 是 run 事件与审批表)。

测试:`tests/unit/harness/` 与 `tests/integration/harness/`(每模块一文件);
端到端冒烟在 `tests/integration/harness/test_end_to_end_smoke.py`
(旧格式项目导入→全链→重启恢复);schema 测试在 `tests/integration/storage/`。

实施票(每张票写明允许文件/禁止项/验收):`docs/harness/tickets/B1..B10`。

## 3. 要参考的 MD

- `docs/harness/README.md` — 模块索引与决策点
- `docs/harness/agent-harness-design-v0.3.md` — 架构权威(55 项锁定决策;重点 §15、§21-24、§41-47、§52-57、§63-64、§73 附录 D)
- `docs/harness/agent-implementation-backend-contract-v0.1.md` — 接线契约(重点 §2 所有权矩阵、§4、§5.2、§10)
- `docs/handoffs/2026-08-14-opencode-handoff.md` — 接手说明、环境坑、验证命令
- `docs/handoffs/2026-08-14-r4-compile-context-dcp.md` — compile_context 门面设计决策
- `docs/harness/tickets/` — B1–B10 实施票(范围与验收)

## 4. 验证命令(工作树内执行)

```text
.venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp\pytest
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

已知环境坑(handoff §6):测试必须带 `--basetemp`;不要用 PowerShell
Get-Content/Set-Content 处理 UTF-8 源码;FTS5 unicode61 不切分中文
(检索词用完整中文 token);`test_windows_scripts.py` 有一个与 Harness
无关的 GBK 环境失败,main 上同样存在,可忽略。

## 5. 检查要点(建议顺序)

1. 边界测试:`tests/unit/harness/test_harness_boundaries.py` 锁定
   domain/core 不 import harness;
2. 端口与事件:run_engine 注入 compile_step/draft_stream 后,事件序列
   (RUN_CREATED→…→COMPLETED)与设计 §63 词汇一致;
3. 端到端:跑 `test_end_to_end_smoke.py`(含重启恢复断言);
4. 权限与审批:网关对核心工具全部 ALLOWED、PROPOSAL_ONLY 需幂等键、
   批准后才落库(B3);
5. 模型输出不可信:所有进后端 DTO 前都经构造校验(B3/B5/B9)。

## 6. 边界声明

本指导只覆盖 Harness 本身。前端(UI 重构)由其他人负责;后端领域与旧
Pipeline 的改动不在本次检查范围。发现任何需要改后端 Facade 才能跑通
的地方,先记录问题,不要直接改后端。
