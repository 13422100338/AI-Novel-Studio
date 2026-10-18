# H0 步骤 4.3:inspect_subjects 公共门面(适配)

- 日期:2026-08-14
- 依据:H0"reuse or adapt the existing Subject authority";契约 §A.2 inspect_subjects;
- 分支:ds/r3b-q1 续用

## 目标

有界主体查看门面:SubjectInspectionRequest(subject_ids)-> SubjectRepository
get/list_aliases -> 本能力自有 SubjectInspection DTO(canonical_name/type/
active/aliases)。未知 ID fail closed(ValueError)。只读,无持久化。

## 允许文件

- 新增 src/ai_novel_studio/application/subject_inspection_service.py
- 新增 tests/integration/application/test_subject_inspection_service.py
- 新增 docs/handoffs/2026-08-14-h0-step4-subject-inspection-ticket.md

## 禁止事项

- 无 schema 修改;不改 SubjectRepository
- 不做别名解析/合并提案(H1/DCP 范围)
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿 + 既有 subject 测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
