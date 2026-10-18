# HARNESS-V1-A2:Model Role Binding + Model Adapter + Usage Meter

- 日期:2026-08-14
- 设计来源:v0.3 §35、§15.2、§66;契约 §12"可立即独立实现"第 2 项
  (ModelAdapter / Streaming / UsageMeter)
- 分支:agent/ai-agent-v1;基线:A1 提交 1c25d19

## 目标

- 三个逻辑角色 AGENT / CHAPTER_DRAFT / COMPACTION 的冻结绑定
  (run 开始后不变,换模型只影响新 run,设计 §35)
- HarnessModelAdapter:通过绑定把角色路由到现有 LLMGateway 的 TaskPurpose;
  complete / complete_json(复用 LLMContractRunner)/ stream 三个表面
- HarnessUsageMeter:把共享 UsageTracker 的按目的记录按角色拆账,
  并标注 ACCURATE / ESTIMATED / UNKNOWN(设计 §66)

## DCP-2(Harness 包结构,需作者知悉)

设计文档推荐逻辑模块树 + 契约 §3 依赖方向要求 Harness 与 Backend Domain
物理分离。本票把 A1 的三个模块移入新包 src/ai_novel_studio/harness/:

- domain/agent_run.py -> harness/run_state.py
- application/harness_event_store.py -> harness/event_store.py
- infrastructure/storage/harness_event_repository.py -> harness/event_repository.py

schema_migrations_v21.py 留在 infrastructure/storage(迁移注册表是后端机制,
无法挪走)。并新增边界测试:domain/ 与 core/ 不得 import ai_novel_studio.harness。

## 允许文件

- 新增 harness/__init__.py;移动 run_state.py / event_repository.py / event_store.py
- 新增 harness/model_roles.py / model_adapter.py / usage_meter.py
- 移动测试:unit/harness/*、integration/harness/test_event_store.py
- 修改 tests/test_package_layout.py(planned boundaries 加入 harness)
- 新增 docs/harness/tickets/A2-model-roles-and-adapter.md

## 禁止事项

- 不新增 schema / 迁移 / 表(用量暂不落库;ModelRequestManifest 持久化留给 A4)
- 不修改 LLMGateway / UsageTracker / LLMContractRunner / schemas
- 不建立第二套模型层或重试策略
- 不修改 main

## 策略

- 绑定在 adapter 构造时冻结;角色重复或目的重复 -> ValueError
- 未绑定角色调用 -> UnboundModelRoleError
- 用量测量:全部记录 estimated=False -> ACCURATE;任一 estimated -> ESTIMATED;
  该角色无记录 -> UNKNOWN

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage/test_harness_schema.py tests/test_package_layout.py -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio

(Windows 本地需 --basetemp,已知 P0-2 环境问题)
