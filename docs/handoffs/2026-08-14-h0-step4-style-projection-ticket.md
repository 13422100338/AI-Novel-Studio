# H0 步骤 4.2:build_style_projection 公共门面(适配)

- 日期:2026-08-14
- 依据:H0"reuse or adapt the existing Style authority";契约 §A.2 build_style_projection;
- 分支:ds/r3b-q1 续用

## 目标

有界样式投影门面:StyleProjectionRequest(书/场景/人物/章范围 + 采样开关)
-> StyleRetriever.for_task -> 本能力自有 StyleProjection DTO(规则/样章/
不合格候选四元组 + projection_id + created_at),域记录复用 StyleRule/
StyleSample/StyleSampleReviewCandidate。

## 允许文件

- 新增 src/ai_novel_studio/application/style_projection_service.py
- 新增 tests/integration/application/test_style_projection_service.py
- 新增 docs/handoffs/2026-08-14-h0-step4-style-projection-ticket.md

## 禁止事项

- 无 schema 修改;不改 StyleRetriever/StyleRepository
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿 + 既有样式测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
