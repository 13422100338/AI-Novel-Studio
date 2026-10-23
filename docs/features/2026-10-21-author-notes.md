# 创作笔记功能票 N1

用户要求：笔记与正文、大纲并列放在顶部；讨论细纲后可保存、编辑浏览；人物、文风、注意事项同样可记；正文每次由作者决定是否附笔记原文，或由 Codex 整理要点后交给写作模型。

工作树：`novel-notes-workspace/AI-Novel-Studio`，分支 `codex/writing-notes`。基线 e7d7495；承接上一前端票的未提交界面改动，上一工作树保持原样。

## 最小闭环与语义

1. 顶部“正文 / 大纲 / 笔记”。笔记模式左侧显示笔记列表，中央 Markdown 阅读和源码编辑，保留 AI 助手。
2. 笔记类型为细纲、人物、文风、注意事项、其他；类型仅帮助浏览，不建立知识图谱。
3. 笔记属于 AUTHOR_NOTE，是作者的计划/指导材料，不是正式正文事实。保存或修改笔记不启动正文模型。
4. 本次写作模式 NONE / FULL / SUMMARY；默认 NONE。作者勾选笔记并选模式。FULL 附完整原文；SUMMARY 由 Codex 读取已选笔记后传入整理要点。任何模式仍走现有正文输入确认。
5. 选中的笔记、笔记修订或模式改变，旧输入提案失效。源笔记、原文摘要及生成输入保留来源信息，不静默截断，不自动采用正文。
6. 小说 MCP 提供列出、批量读取、创建、更新笔记工具。新笔记 ID 由程序生成；更新必须携带 expected_revision。只读工具与写服务独立，保存采用追加修订，旧版保留；不提供任意文件路径或删除工具。

## 存储提案（不迁移数据库）

项目独立 `notes/<uuid>.00000001.json` 等扁平追加修订文件，避免新建时半成品目录成为文档。文件严格字段集合：schema_version=1、project_id、note_id、revision、title、kind、content、source_hash、previous_revision_hash、created_at。

- source_hash 是 content 的小写 SHA-256；previous_revision_hash 是上一修订规范 JSON 的 SHA-256，首版为 null。UTC 时间采用 `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`。
- title 1–200 字，kind 固定枚举 OUTLINE / CHARACTER / STYLE / CAUTION / OTHER；content 至多 200000 字。内容允许换行/制表，拒绝 NUL、其他 C0 控制字符、未配对代理码点。预解析 JSON 上限 1 MiB。
- 扫描上限：200 个笔记、单笔记 2000 修订、项目 10000 个修订文件、总计 64 MiB；超限明确失败而不裁剪。MCP 批量至多32篇，输出总字节上限2 MiB，超限要求缩小选择。
- 文件名 UUID 必须标准小写且与内部 note_id 一致；文件序号与 revision 一致，从1连续递增。检查完整链及所有历史内容哈希，损坏历史/缺号/重复/非普通文件/软链接/reparse 均 fail closed。root 只允许合法修订、受控临时文件及 `.write.lock`；其他条目报错，绝不删除。
- 写入：项目级线程锁与非阻塞 OS 文件锁串行化写操作；在同目录独占临时文件中写完 UTF-8、flush/fsync、重读校验，再排他发布最终文件。Windows 采用不覆盖目标的 os.rename；POSIX 采用 os.link(create-if-absent)，再移除本次临时文件。最终修订绝不使用 os.replace；临时文件不参与扫描。保存失败保留旧修订；读操作不创建目录、锁或临时文件。
- 笔记在显式保存或离开页面/项目时保存，不为每次键入追加修订。保存失败阻止切换并保留编辑。

规范 JSON 算法固定为 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`，无 BOM、无尾随换行；读取必须重新序列化并要求原文件字节完全相同。previous_revision_hash 对上一修订的这些规范字节取 SHA-256。

临时文件严格命名 `.<note_uuid>.<8位revision>.<32位writer_nonce>.tmp`，至多32个，也计入10000文件/64MiB总扫描限额，每个至多1MiB。正常写入者只清理自己本次 nonce 的临时文件；遗留临时文件不视作正式修订，不静默删除。发现遗留文件时正常读操作仍可读已发布的有效修订，但写入口抛 NoteRecoveryRequired。笔记页提供显式恢复/放弃入口：恢复仅接受完整规范 JSON、正确项目身份、紧邻当前 head 的修订及 previous hash，先通过当前持锁写入者的新临时文件排他发布，再把遗留文件移入项目 `notes-recovery/` 保留；放弃也只移入该目录，保留内容，不删除。只接受扫描产生的受控临时文件句柄，不接受任意路径；归档目标排他创建，软链接和边界检查同 notes 目录。恢复不通过 MCP 暴露，不自动进行。

### 输入身份冻结

WriterInputPlan 增加 note_mode、有序 NoteRef(note_id, revision, source_hash)、选择/顺序 fingerprint、note_summary 和 summary_hash、完整源笔记快照。FULL 的完整原文进入 messages；SUMMARY 的原文仅作为来源快照保留，实际 messages 只附 Codex 已整理的摘要及来源身份。摘要必须在作者确认前准备并显示；确认后绝不重新总结。validate 重新读取所有选中笔记 head 并比对当前选择顺序/模式，任一修订、哈希、顺序或模式变化即 stale。WriterInputRepository 元数据保存以上字段和源笔记快照。

模式严格互斥：NONE 的 NoteRef 为空、summary/hash 均为 null、messages 不含笔记；FULL 为1–32个有序且不重复的 NoteRef、summary/hash为null，按顺序附原文；SUMMARY 为1–32个 NoteRef、1–20000字非空 summary，summary_hash=sha256(summary UTF-8)，原文不得进入 messages。任何跨变体组合立即报错。MCP 的 notes_summary 默认空字符串，NONE/FULL 非空即拒绝，SUMMARY 空白即拒绝；它是未经确认的候选，必须经过同一输入提案预览与作者确认。模式和有序选择以作者在软件中设置的选择快照为准，Codex不能自行更换选择；空选择只能处于NONE。

稳定 MCP 参数合同（全部禁止路径参数）：

- `list_novel_notes(offset: int=0, limit: int=100)`，offset 0–200、limit 1–100，只读返回元数据。
- `read_novel_notes(note_ids: list[str])`，1–32个唯一标准UUID，批量完整原文；上限前述2MiB，明确 truncated=False 或报错。
- `create_novel_note(title: str, content: str, kind: Literal[OUTLINE,CHARACTER,STYLE,CAUTION,OTHER]=OTHER)`，使用上文长度/控制字符规则，程序分配note_id并返回revision=1。
- `update_novel_note(note_id: str, expected_revision: int, content: str, title: str|None=None, kind: Literal[...]|None=None)`，expected_revision 1–2000，None保持原值；错误修订失败，不覆盖或静默合并。

前两个工具 readOnlyHint=True；后两个工具 readOnlyHint=False、destructiveHint=False、openWorldHint=False、idempotentHint=False，写入口由 NovelNoteService 独立处理并可在项目切换时撤销。写能力只限于作者明确要求的笔记创建/更新，不自动改变写作选择，不调用正文模型，不回写正文。

## 实施范围

- 新增 `domain/author_note.py`、`infrastructure/storage/note_repository.py`、`application/novel_note_service.py`。
- 前端新增 `bridge/notes_bridge.py`、`NotesPage.qml`、笔记导航/输入选择组件，接入 Facade 和顶部页签。
- 只读扩展 `application/novel_read_service.py`、`infrastructure/mcp/novel_server.py` 的 list/read 工具；create/update 由独立 `NovelNoteService` 写入口处理，write annotation 明确 readOnlyHint=False。更新 NovelMcpEndpoint 工具目录、`application/codex_session_service.py` 接线和创作说明、`infrastructure/codex/app_server.py` 工具白名单校验对应测试。
- 扩展 `application/outline_writer_input.py`、`novel_writer_service.py`、`outline_writer_service.py` 和 MCP generate 参数 notes_summary；正文输入的笔记放在完整大纲和本次要求之后、正文参考资料之前。
- 前端接线涉及 `mock_novel_studio_facade.py`、`codex_session_bridge.py`、App/WorkspaceTabs/ContextSidebar/CreativeAgentPanel；选中文档/模式进入当前 NovelReadService 的项目限定选择快照。
- 测试包含 notes repository/service/input/MCP 与 NotesBridge/QML；按存储、模型输入、界面闭环分别验证后再继续下一部分。
- 仅临时项目验证，不打开作者实际小说，不迁移现有数据库，不修改全局 Codex/OpenCodex 配置，不提交、合并或部署。

## 验收

- 真实创建、编辑、保存、重开、冲突保护和修订读取。
- 顶部入口与笔记导航；切换/关闭时保存失败保留编辑。
- NONE 不带笔记；FULL 含完整选中文本；SUMMARY 只附已确认要点并记录来源；笔记变更阻止旧提案。
- MCP 列读存严格绑定当前项目，拒绝越界路径与错误修订。
- 用模拟模型捕获最终输入，核对预览与实际消息一致；实际窗口验证 Markdown 表格和笔记选择。

## 主控与交付状态

2026-10-21，原主控第三轮复审因额度限制中断。作者在本对话明确授权“由你接管并完成笔记功能”，本票主控与最终验证由当前对话负责；该授权不涉及其他旧 lane。前两轮阻断项已纳入上述冻结合同，未绕过作者输入确认。

本票已实现存储、读写服务、MCP、笔记输入与界面闭环。沿用上一票界面，顶部为正文 / 大纲 / 笔记。笔记支持 Markdown 表格阅读、源码编辑、保存/重载、修订预览与另存新修订、导入导出和未完成保存恢复；左侧和聊天底部均可选择写作笔记。Codex 可通过项目限定 MCP 列读、创建和按修订更新笔记，不能改变作者选择的引用方式。

补充接线：get_novel_context.active_note 告知助手当前笔记及未保存标志；开始新对话和确认正文输入前先保存编辑。输入确认界面显示笔记引用方式，并逐条展示实际消息；SUMMARY 原文只保留在来源快照，不传给写作模型。项目备份也纳入 notes 与 notes-recovery 目录。

## 验证记录

- 存储测试12项通过，包括旧版本保留、并发/过期编辑、历史损坏、部分暂存保留、完整暂存恢复、发布失败及备份收录。
- 正文输入测试36项通过（包括新笔记测试7项），核对 NONE/FULL/SUMMARY、确认前零模型调用、笔记修订/方式/顺序变化导致旧提案失效、预览与发送消息一致。
- MCP 及传输测试18项通过，包括真实本地 HTTP MCP 的创建/批量读取/更新、准确权限注解、错误修订和撤销写入口。
- 主回归121项通过，另1项旧审查测试因 Windows 临时路径过长失败；使用短 basetemp 单独重跑通过，未修改无关正文存储代码。
- 最后补充 Codex 会话/界面、备份及笔记 UI 回归52项通过（与前述集合有重叠）。Ruff 通过；13个相关源模块 MyPy 通过；编辑器 npm 构建与 launch.ps1 启动检查通过。
- Windows 实际窗口截图在本工作树 `.test-temp/nv-final2/`：notes-reading.png、notes-source.png、notes-narrow.png、notes-picker.png、notes-input-review.png、notes-candidate.png。实际鼠标和键盘操作覆盖顶部页面、选择器关闭、输入审阅与确认；模拟模型仅在确认后调用1次，收到冻结的要点，未收到原笔记全文；正式正文未改动；QML 警告为0。
- 最后补充笔记 MCP / Codex 传输与会话测试31项通过，覆盖新工具接线。笔记批量读取的宿主输出上限与服务端2MiB读取界限匹配，并明确要求遇到截断提示时缩小批次重新读取。最终启动检查和差异检查通过。
- 所有验证仅使用本工作树内的虚构临时项目与模拟正文模型；未调用付费写作模型，未打开作者小说、修改密钥或切换全局模型路由。Pydantic lifespan forward-reference 警告来自既有依赖，未影响测试。

## 使用路径

1. 在软件里与 Codex 商讨，要求“把这些结果保存为细纲笔记，先不生成正文”。
2. 到顶部笔记页继续阅读、编辑或补充人物/文风/注意事项；手动保存或离开页面时保存。
3. 正式写作前，在笔记页或聊天底部“笔记”选择器勾选材料，选择不附 / 原文 / 要点。
4. 对 Codex 提出写作要求，在任务卡“查看并确认输入”中检查完整输入，确认后生成候选。

工作树启动入口为本目录的 `启动程序.bat`。改动尚未提交、合并或替换桌面旧入口；原前端工作树和桌面检出保持原样。下一步是作者在独立功能版中实际使用并决定整合时机。
