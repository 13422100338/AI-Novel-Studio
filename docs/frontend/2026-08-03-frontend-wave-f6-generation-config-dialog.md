# Frontend Wave F6 交付记录（生成配置弹层）

> 分支：`codex/frontend-wave-f1`（F5 提交之上）
> 日期：2026-08-03
> 范围：「生成草稿」改为弹层配置（目标字数 / 输出 Token / 创作档位 / 采用前审校），
> 配置透传真实生成端口；不改任何后端接口。

## 1. 交付内容

- 新增前端 `GenerationConfig` DTO（`bridge/draft_port.py`）：
  `target_words / output_token_limit / mode(CreationMode) / audit_policy(AuditPolicy)`；
- `DraftPort.prepare(chapter_id, revision, config)` 与
  `ProjectSessionDraftPort.prepare` 改为消费完整配置（不再硬编码 BASIC/MINIMAL/8192）；
- Facade 增加生成配置状态与槽：
  - 属性：`generationTargetWords`（100–100000，默认 800）、
    `generationOutputTokenLimit`（256–32768，默认 8192）、
    `generationMode`（BASIC/STANDARD/STRICT，默认 BASIC）、
    `generationAuditPolicy`（MINIMAL/STANDARD/DEEP，默认 MINIMAL）；
  - 越界值钳制、非法枚举忽略；`requestDraft` 把当前配置传给端口；
- 新增 QML `GenerationConfigDialog`（components/）：
  - 「生成草稿」按钮 → 打开弹层（打开时从 Facade 读取当前值）；
  - 目标字数 / 输出 Token SpinBox、创作档位 / 采用前审校 ComboBox；
  - 「开始生成」写入 Facade 配置后启动生成；「取消」仅关闭；
- 演示模式同样生效：配置状态可改，「开始生成」走原有 mock 建议流程。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/draft_port.py                 GenerationConfig + prepare(config)
├── bridge/mock_novel_studio_facade.py   配置状态/属性/槽 + 传参
├── qml/components/GenerationConfigDialog.qml  弹层（新增）
└── qml/pages/WritingPage.qml            生成草稿 → 打开弹层
tests/ui_qml/test_mock_facade.py         默认值/校验/配置传参（+3）
tests/ui_qml/test_draft_port.py          prepare 签名适配
tests/ui_qml/test_qml_shell.py           弹层交互 + 旧流程适配（+1）
docs/frontend/2026-08-03-frontend-wave-f6-generation-config-dialog.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 87 passed |
| 完整 `pytest` | 909 passed |
| Ruff / MyPy（195 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- 端口直连测试：`prepare` 收到 `GenerationConfig` 并按其 mode/policy/limit/words
  调用 `ProjectGenerationSession.prepare_generation`（真实 stub gateway）；
- facade：默认值正确；越界钳制（100 / 32768）；非法枚举忽略；
  配置随 `requestDraft` 原样传入 FakeDraftPort；
- QML：点「生成草稿」→ 弹层可见 → 修改四个控件 → 点「开始生成」→
  facade 配置更新 + mock 建议生成。

## 4. 接线细节、风险与下一步

- STRICT/DEEP 会触发 `requires_forced_pre_accept_audit`（采用前审校），真实网关下
  采用可能被审校阻塞——这符合现有后端安全边界，facade 会把失败信息如实显示；
- 弹层打开时从 Facade 回填当前值，取消不改变配置；
- 下一步建议：
  1. 草稿三视图（当前正文 / AI 草稿 / 差异）与段落级采用；
  2. Token/费用显示（复用 `UsageSnapshot` 语义）；
  3. 或进入 F2 剩余只读接线（人物/记忆/审校数量概览与页面骨架）。
