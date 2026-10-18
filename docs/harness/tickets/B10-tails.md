# HARNESS-V1-B10:小尾巴四件套(Manifest 落库 / 保留清理 / Skill 装载 / 取消令牌续接)

- 日期:2026-08-15
- 设计来源:v0.3 §15.2、§32、§54-§55、§67;handoff 2026-08-14 §4(B10)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- Schema:本票占用 v24(handoff 已预授权:"下一个新迁移从 v24 起")
- 依赖:A1/A4/A5 均已实现

## 目标(四节,互不依赖)

### B10a ModelRequestManifest 落库

- schema v24:harness_model_request_manifests 表(role/cache_status CHECK,
  run_id FK,索引 (run_id, created_at));注册进迁移注册表;
- harness/model_request_manifest_repository.py:save/get/list_for_run/
  latest_for_run;模型清单构造时全量校验(现有 dataclass 校验);
- 机械更新 11 个存储测试的 LATEST==23 → ==24 断言 + harness schema 测试
  新增 v24 表断言。

### B10b Artifact 保留清理

- ArtifactBackend 协议补 list_ids()/delete();FileArtifactBackend 实现
  (ProjectArtifactBackend 继承);
- harness/retention.py:ArtifactRetentionService.cleanup(now 可注入):
  按 kind 策略——TOOL_RESULT/SUMMARY_REVISION 默认保留 30 天,过期删除;
  DRAFT_CANDIDATE/PARTIAL_DRAFT/DRAFT_CHECKPOINT 为创作产物永久保留
  (设计 §67);返回 ArtifactCleanupResult。

### B10c Skill 运行时装载

- harness/skill_runtime.py:SkillRuntimeService(store, catalog):
  load_for_run(未知 Skill 报错;追加 SKILL_LOADED 事件,payload 含
  skill_id/version;闭 run 由事件存储拒绝)→ 进程内缓存完整 Skill;
  unload(run_id) 清缓存只留事件记录(设计 §32);loaded_ids(run_id)
  从事件日志派生(重启后权威)。

### B10d 恢复中心续接取消令牌

- run_engine.py:recover_open_runs():为所有非 CLOSED_STAGES 的存量 run
  重建进程内 CancelToken(重启后 cancel/stream_draft 可用);已关 run 不重建。

## 允许文件

- 新增 schema_migrations_v24.py;修改 schema_migrations.py(注册 v24)
- 新增 harness/model_request_manifest_repository.py / retention.py / skill_runtime.py
- 修改 harness/artifacts.py / run_engine.py
- 机械更新 tests/integration/storage/ 下 11 个 LATEST 断言文件
- 新增 tests/integration/harness/test_model_request_manifest.py、
  tests/unit/harness/test_retention.py、tests/integration/harness/test_skill_runtime.py
- 修改 tests/integration/harness/test_run_engine.py、test_harness_schema.py
- 新增 docs/harness/tickets/B10-tails.md

## 禁止事项

- 不触碰 v1-v23 既有迁移;不建第二套清单存储;
- 不改 ContextManifestRepository / 旧管线;不合并 main

## 已知限制

- 胶囊 last_model_request_manifest_id 尚未接 Manifest 库(留后续小接线);
- 保留策略仅按 kind 分级,不按 run 引用关系(设计 §67 默认 30 天即此);
- Skill 装载缓存为进程内,重启后以事件日志为准

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
