---
name: novel-edit
description: 在小说工作台中重写、润色、精简、扩写、生成草稿或续写，交由独立正文写作模型生成候选。
---

围绕作者指定范围完成小说编辑。先调用 get_novel_context 和 get_novel_constraints，确定当前章节、修订、选文及作者章要求。

有选文时，以该选文为默认处理范围。将原文和必要上下文直接写入 generate_novel_draft 的 instruction，明确“仅编辑这段选文”，返回选文对应的候选正文，禁止扩大为整章。选文带有截断标记时先请作者缩小范围，不能把局部当完整选文。无选文且范围不明时先确认范围。

润色改善措辞和句式；精简去掉冗余；扩写补充细节；重写调整表达。以上操作保留人物、情节事实、视角、时间顺序和作者约束。生成草稿与续写遵循作者目标，需要其他章节时使用 read_novel_chapters 批量读取。

调用 generate_novel_draft 时使用当前 chapter_id 和 expected_revision，保留已保存章要求，素材标记 EDITOR_BUFFER、FORMAL_MANUSCRIPT 或作者附件。正文交由独立写作模型生成，不用聊天回复代替写作模型，不写入或替换正式稿。

生成后简短说明处理范围并提示查看任务卡。无需终端、文件写入、Git 或其他应用。
