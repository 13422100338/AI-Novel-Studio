# Frontend Wave F10 交付记录（Token 芯片悬浮明细）

> 分支：`codex/frontend-wave-f1`（F9 提交之上）
> 日期：2026-08-03
> 范围：状态栏 Token 芯片悬浮显示调用/失败明细；不改任何后端接口。

## 1. 交付内容

- `StatusChip` 新增 `tooltipText` 属性 + `ToolTip`（300ms 延迟，hover 显示）；
- `App.qml` Token 芯片 `tooltipText: "输入 / 输出 · " + Facade.usageCallsText`，
  即「输入 / 输出 · N 次调用[ · M 失败]」；
- 复用 F8 的 `usageCallsText`，无新增后端依赖。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/qml/components/StatusChip.qml   tooltipText + ToolTip
src/ai_novel_studio/ui_qml/qml/App.qml                     Token 芯片 tooltipText
tests/ui_qml/test_qml_shell.py                             悬浮内容断言（并入 F8 用例）
docs/frontend/2026-08-03-frontend-wave-f10-usage-tooltip.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 119 passed |
| 完整 `pytest` | 941 passed |
| Ruff / MyPy（198 文件）/ `git diff --check` | 全部通过 |

断言：生成完成后 Token 芯片 `tooltipText == "输入 / 输出 · 1 次调用"`。

## 4. 风险与下一步

- ToolTip 为 Qt Quick Controls 标准实现，offscreen 下仅验证属性绑定，未验证
  悬停视觉（与既有滚动条警告同类，属 offscreen 环境限制）；
- 下一步建议：打包前 QML 资源清单与入口评估（F11，只读审计 + 前端文档）。
