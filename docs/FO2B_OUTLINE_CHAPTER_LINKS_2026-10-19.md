# FO-2b：大纲与正式章节的轻量关联

日期：2026-10-19。状态：实现及临时项目验证完成，未提交或推送。
分支：`codex/full-outline-architecture`；沿用 FO-1／FO-2a 的独立工作树，基线 `3d196bd`。
依据：[完整大纲方案](FULL_OUTLINE_WORKFLOW_2026-10-18.md)、[大纲编辑工作区](FO2A_OUTLINE_WORKSPACE_2026-10-19.md)。

## 使用方式

打开“大纲”，将光标放在某个事件行，点击“章节关联”：

1. 选择正式章节并点“插入关联”。软件在当前行后插入普通 Markdown 相对链接并保存。可重复选择，关联多个不连续章节。
2. 当前文档已有的普通章节链接也会被识别；新记录为“待确认”。勾选并点“确认所选关联”才成为当前大纲版本的已确认关系。
3. 卡片可以打开正式章节、跳回大纲位置、查看确认记录；面板可关闭，不常驻占用编辑区。
4. 修改任意登记大纲、重导入、回退版本或调整文档顺序后，已有关系与历史保留，但需要重新确认。无改动保存和无变化排序不会使确认失效。
5. 无法确定原位置时显示“位置待定位”。作者把光标放到含该章节链接的正确行，再点“定位到当前行”；不会按相似事件文字自动确认。
6. 从 Markdown 删除链接或删除目标章节后，旧记录仍在。作者可以“确认移除”，并通过“显示已确认移除的历史关联”查看；不会擅自把链接插回正文。

Markdown 仍是主要资产，不添加固定事件实体、人物图谱或锚点。重导入时，只有指向当前项目已登记正式章节路径的链接才能映射到章节 ID；外部来源的未知路径需手动重新选择。
AI 生成的普通链接文本可以由作者编辑或导入后检查；本票尚未增加 Codex 专用关联提案／应用工具，不自动接受 AI 建议。

## 存储与版本约束

- v27 只新增 `outline_chapter_links` 及索引：文档 ID、目标章节 ID／标题、原文位置／引用、最后确认的大纲包指纹、活动状态和追加式审阅记录。
- 不新增事件、关系网络或摘要表，不删除旧记忆表，不改写章节正文。章节目标不设级联删除外键，因此章节移除后仍可追溯原关系。
- 大纲包指纹覆盖全部登记文档的身份、修订、原文哈希、排序与更新时间。实际重排在事务内单调推进已有更新时间；即使重排后还原或系统时钟回退，也不能复活旧确认。
- 批量确认先校验全部所选记录，再在同一事务内写入；其中一项失效则全部失败。重复确认当前已确认记录不会追加重复历史。
- 界面持有的审阅指纹、显示中的原文修订及哈希必须与操作相符；后台继续校验实时大纲包，防止确认未展示的新版本。
- 无法唯一匹配的重复链接保留原记录，等待作者定位；已移除链接重新出现在原文时创建新的待确认记录，保留旧移除历史。
- 解析仅匹配当前项目的登记路径，不跟随远程 URL、不探测未知文件或网络共享；跳过图片、行内代码和围栏代码中的链接。
- 扫描读取大纲原文与章节元数据，只有作者点击“打开章节”才走正常正文载入流程。打开前保存当前正文；保存失败则停止跳转，保留缓冲区。
- 关联索引失败单独显示错误，不能撤销或清空已经保存的 Markdown；重新扫描成功后才恢复确认操作。

## 改动位置

- `domain/outline_link.py`：关联、审阅记录与校验后的快照。
- `core/outline_links.py`：普通相对链接解析、路径匹配、链接插入。
- `infrastructure/storage/outline_link_repository.py`、`schema_migrations_v27.py`、`schema_migrations.py`：关联存储、事务、迁移及确认失效。
- `infrastructure/storage/outline_repository.py`：重排元数据版本；不改变 Markdown 内容修订。
- `application/outline_service.py`：章节选择与插入内容准备，复用原有大纲保存。
- `ui_qml/bridge/outline_bridge.py`、`mock_novel_studio_facade.py`：面板状态、版本校验、安全章节导航。
- `ui_qml/qml/components/OutlineLinksPanel.qml`、`pages/OutlinePage.qml`：可关闭的关联面板。
- 新增解析、存储、桥接及实际 QML 测试；更新迁移版本断言与旧 QML 测试对象生命周期夹具。
- 简短中英文 README 与路线文档同步当前能力。

以上源码路径相对于 `src/ai_novel_studio/`。

## 验证与边界

- 本票新增 32 项测试，覆盖普通链接、批量确认、改纲／重排失效、旧 token 拒绝、明确移除、历史保留、迁移与真实 QML 操作。
- 存储、FO-1 服务及草稿采用／恢复回归 377 项通过；界面、应用与文本处理回归 147 项通过，两组共 524 项，无跳过。
- Ruff、11 份相关 Python 源码的 MyPy 与差异检查通过。
- 独立只读复核通过；待确认、已确认及改纲后重新确认完成离屏截图检查，相关 QML 无加载警告。
- 旧 QML 测试曾在窗口销毁时提前释放 Facade／Theme，导致跨用例回调错误；修正测试夹具的引用保留和延迟销毁处理，单独 38 项回归通过，未修改对应业务模型。
- 所有验证使用临时项目；未打开、迁移或修改作者小说数据库，未调用真实模型。
- 超大大纲、极多关联及长期积累审阅记录的性能尚未压测；本票不改变 FO-1 的 20MB 存储限制。

设置 `PYTHONPATH` 为本工作树的 `src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`，使用新临时目录运行：

```powershell
python -m pytest tests/unit/test_outline_link_markdown.py tests/integration/storage/test_outline_links.py tests/ui_qml/test_outline_link_bridge.py tests/ui_qml/test_outline_links_panel.py -q -p no:cacheprovider
python -m pytest tests/integration/storage tests/integration/application/test_outline_service.py tests/integration/generation/test_generation_acceptance_and_recovery.py -q -p no:cacheprovider
python -m pytest tests/ui_qml/test_outline_page.py tests/ui_qml/test_outline_bridge.py tests/ui_qml/test_project_wiring.py tests/ui_qml/test_mock_facade.py tests/ui_qml/test_qml_shell.py tests/unit/test_outline_markdown.py tests/integration/application/test_outline_workspace.py tests/unit/test_outline_link_markdown.py tests/ui_qml/test_outline_link_bridge.py tests/ui_qml/test_outline_links_panel.py -q -p no:cacheprovider
```

下一票：FO-3，将完整大纲原文接入 Codex 每轮创作输入并验证容量、恢复、分支与压缩边界。本票没有改变模型输入，独立正文模型仍待 FO-4 接入。
