# HARNESS-V1-B7:正文检查点与共享检查点基础设施对接

- 日期:2026-08-15
- 设计来源:v0.3 §42、§53.1、§67-§68;handoff 2026-08-14 §4(B7)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:B2 流式检查点(已完成);后端 CheckpointRepository / ProjectLayout 已合入 main

## 目标

把 Harness 正文检查点接入项目级共享恢复基础设施(§53.1:底层共享
Artifact 存储,对象类型必须分开;不得与旧 Pipeline 各建互不相认的恢复目录)——

1. ProjectArtifactBackend:Harness ArtifactStore 的项目级后端,工件落在
   `<project>/.ai_pipeline/artifacts/<sha256>.bin/.json`(与后端
   `.ai_pipeline/checkpoints/` 同恢复树,备份/导出自然携带;首写自动建目录,
   不改 ProjectLayout);
2. 对象类型分离:ArtifactKind 新增 DRAFT_CHECKPOINT——流中稳定检查点
   存 DRAFT_CHECKPOINT,取消/失败残稿仍为 PARTIAL_DRAFT,完成稿为
   DRAFT_CANDIDATE(与 §53.1 RUN_CHECKPOINT/DRAFT_CHECKPOINT/... 分离
   对齐;RUN_CHECKPOINT 留恢复中心票);
3. 持久索引仍由 A1 事件日志承担(CHAPTER_STREAM_CHECKPOINT_SAVED 事件
   携带 artifact_id),不新增表、不碰 schema v24 领地。

## 允许文件

- 修改 src/ai_novel_studio/harness/artifacts.py(新增 kind 与项目级后端)
- 修改 src/ai_novel_studio/harness/draft_stream.py(检查点改存 DRAFT_CHECKPOINT)
- 修改 tests/unit/harness/test_artifacts.py、tests/integration/harness/test_draft_stream.py
- 新增 tests/integration/harness/test_checkpoint_infrastructure.py
- 新增 docs/harness/tickets/B7-shared-checkpoint-infrastructure.md

## 禁止事项

- 无 schema 变更(不建表、不迁移);不改后端 CheckpointRepository / ProjectLayout;
- 不改 ArtifactStore 内容寻址与首写元数据语义;不合并 main

## 已知限制

- 旧 Pipeline 的 generation_checkpoints 表与 Harness DRAFT_CHECKPOINT
  分属不同 run 域,不互相写入(§53.1 只要求共享底层与类型分离);
- RUN_CHECKPOINT 与恢复中心续接留 B10

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness/test_artifacts.py tests/integration/harness/test_draft_stream.py tests/integration/harness/test_checkpoint_infrastructure.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
