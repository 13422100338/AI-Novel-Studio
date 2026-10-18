# H0 步骤 4.4:submit_revision 公共门面(适配)

- 日期:2026-08-14
- 依据:H0"reuse or adapt RevisionImpact";补充文档 Ticket R3 提交边界要求
- 审计结论:ChapterRevisionService.submit_revision 已是统一提交边界,
  人工编辑/AI 接受/修复应用/导入四条路径均已经由它(R2b-C 已集成)。

## 目标

薄门面:RevisionSubmissionRequest(chapter_id/content/source/reason/
expected_revision/invalidate_memory)-> submit_revision -> SubmittedRevision
(复用,含 RevisionImpact 与 FormalMaintenanceResult)。不建第二提交路径。

## 允许文件

- 新增 src/ai_novel_studio/application/revision_submission_service.py
- 新增 tests/integration/application/test_revision_submission_service.py
- 新增 docs/handoffs/2026-08-14-h0-step4-submit-revision-ticket.md

## 禁止事项

- 无 schema 修改;不改 ChapterRevisionService/仓储
- 不改四条既有写入路径(D6 原则:迁移另行)
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿 + 既有修订测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
