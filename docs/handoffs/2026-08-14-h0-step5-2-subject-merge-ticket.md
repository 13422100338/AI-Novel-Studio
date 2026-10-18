# H0 步骤 5.2:Subject 合并预览门面(复用现有事务)

- 日期:2026-08-14
- 依据:H0 步骤 5 DCP D-3/D-4(用户批准推荐项 A);设计 §27.1.1
- 分支:ds/r3b-q1

## 目标

在现有 CharacterIdentityService 合并/撤销事务之上加预览门面:
preview(source, target) 确定性计算——可保留别名、状态事件迁移数、
同章共存冲突数(同一章双方都有状态事件)、可撤销(现有 undo 保证)。
commit = 现有 merge(confirmed_by_user 门禁保留);undo 原样暴露。
MergeManifest 语义复用现有 CharacterIdentityMerge 记录(别名迁移/
事件迁移/撤销状态俱全),不新建近义记录。

## 允许文件

- 新增 src/ai_novel_studio/application/subject_merge_service.py
- 新增 tests/integration/application/test_subject_merge_service.py
- 新增 docs/handoffs/2026-08-14-h0-step5-2-subject-merge-ticket.md

## 禁止事项

- 无 schema 修改;不改 CharacterIdentityService/仓储
- 不做字段级冲突裁决(预览只报告同章共存数,裁决由作者)
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿 + 既有身份合并测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
