# H0 步骤 5.3:最小 ChangeSet + build/commit 门面(方案 A)

- 日期:2026-08-14
- 依据:H0 步骤 5 DCP D-5/D-6(用户批准推荐项 A)
- 分支:ds/r3b-q1

## 目标

三种类型操作:CHAPTER_CONTENT_REPLACE / CHAPTER_TITLE_CHANGE /
REPAIR_APPLY。build = 纯干跑(章节存在 + expected_revision 匹配 + 修复
提案已 VALIDATED,零写入);commit = 顺序执行并映射既有边界
(submit_revision / submit_title_revision / repair apply),首个失败即停,
逐操作结果报告。幂等去重由 Harness 审批层(A8a)负责,门面只校验并记录
idempotency_key。

## 允许文件

- 新增 src/ai_novel_studio/domain/changeset.py
- 新增 src/ai_novel_studio/application/changeset_service.py
- 新增 tests/integration/application/test_changeset_service.py
- 新增 docs/handoffs/2026-08-14-h0-step5-3-changeset-ticket.md

## 禁止事项

- 无 schema 修改;不改既有四个写入边界
- 不做跨章节原子回滚(已知限制:顺序执行,失败后已应用的操作保持,
  由 Harness 审批层保证前置校验;全量事务留 V1.2)
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
