from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DemoChapter:
    id: str
    number: str
    title: str
    word_count: int
    status: str


@dataclass(frozen=True, slots=True)
class DemoVolume:
    id: str
    title: str
    chapters: tuple[DemoChapter, ...]


@dataclass(frozen=True, slots=True)
class DemoCharacter:
    id: str
    name: str
    psychology: str
    motivation: str
    current_goal: str
    recent_activity: str


@dataclass(frozen=True, slots=True)
class DemoMessage:
    role: str
    text: str


@dataclass(frozen=True, slots=True)
class DemoBrief:
    status: str
    fingerprint: str
    warnings: tuple[str, ...]
    sources: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class WorkspaceDemoData:
    project_title: str
    current_volume: str
    volumes: tuple[DemoVolume, ...]
    characters: tuple[DemoCharacter, ...]
    messages: tuple[DemoMessage, ...]
    brief: DemoBrief
    chapter_requirement: str
    generated_requirement: str
    chapter_text: str
    memory_tabs: tuple[tuple[str, str], ...]
    style_rules: tuple[tuple[str, str, str], ...]
    audit_findings: tuple[tuple[str, str, str], ...]

    @classmethod
    def empty(cls) -> "WorkspaceDemoData":
        return cls(
            project_title="未打开项目",
            current_volume="请新建或打开一个小说项目",
            volumes=(),
            characters=(),
            messages=(),
            brief=DemoBrief(
                status="",
                fingerprint="",
                warnings=(),
                sources=(),
                sections=(
                    ("戏剧功能", ""),
                    ("必须事件", ""),
                    ("知识边界", ""),
                    ("叙事线索", ""),
                    ("文风", ""),
                    ("自由空间", ""),
                ),
            ),
            chapter_requirement="",
            generated_requirement="",
            chapter_text="",
            memory_tabs=(),
            style_rules=(),
            audit_findings=(),
        )

    @classmethod
    def sample(cls) -> "WorkspaceDemoData":
        chapters = (
            DemoChapter("chapter-1", "第 1 章", "雪夜来客", 3268, "已确认"),
            DemoChapter("chapter-2", "第 2 章", "没有寄出的信", 2984, "编辑中"),
            DemoChapter("chapter-3", "第 3 章", "旧城钟声", 0, "待创作"),
        )
        return cls(
            project_title="雾港来信",
            current_volume="第一卷 · 潮声",
            volumes=(DemoVolume("volume-1", "第一卷 · 潮声", chapters),),
            characters=(
                DemoCharacter(
                    "character-lin",
                    "林默",
                    "警惕，但被故乡旧事牵动",
                    "确认失踪兄长是否仍然活着",
                    "在不惊动调查者的情况下进入旧港档案室",
                    "收到一封使用兄长旧暗号的无署名来信",
                ),
                DemoCharacter(
                    "character-su",
                    "苏砚",
                    "表面从容，实际担心林默失控",
                    "保护林默并查清来信来源",
                    "说服林默先核实钟楼记录",
                    "从海关旧档案中发现被涂改的日期",
                ),
            ),
            messages=(
                DemoMessage(
                    "assistant", "这一章可以让来信成为行动触发点，但先不要证明寄信人身份。"
                ),
                DemoMessage("user", "保留怀疑，同时让林默主动决定去旧港。"),
                DemoMessage("assistant", "可以。情绪重点放在他明知可能是陷阱，却仍选择靠近真相。"),
            ),
            brief=DemoBrief(
                status="草稿",
                fingerprint="brief-demo-a31f",
                warnings=("钟楼记录的来源尚未人工确认",),
                sources=(
                    "当前章要求（最高优先级）",
                    "人工大纲",
                    "上一章全文",
                    "人物聚合状态卡",
                    "叙事线索 CL-04",
                ),
                sections=(
                    ("戏剧功能", "迫使林默从被动等待转为主动调查。"),
                    ("必须事件", "来信出现；林默识别暗号；决定前往旧港。"),
                    ("知识边界", "林默只知道暗号真实，不知道寄信人和兄长状态。"),
                    ("叙事线索", "强化真实伏笔 CL-04；保留误导线索 CL-07。"),
                    ("文风", "近距离第三人称；克制；避免解释恐惧。"),
                    ("自由空间", "允许自行设计来信出现的位置和现场细节。"),
                ),
            ),
            chapter_requirement=(
                "本章让林默收到使用兄长旧暗号的无署名来信。保持寄信人身份未知，"
                "重点描写他明知可能是陷阱，仍主动决定前往旧港调查。"
            ),
            generated_requirement=(
                "正式要求：林默在雪夜发现无署名来信并确认兄长旧暗号真实；"
                "不得揭示寄信人或兄长生死；结尾由林默主动决定前往旧港，"
                "情绪保持克制，不直接解释恐惧。"
            ),
            chapter_text=(
                "雪是在傍晚以后才密起来的。\n\n"
                "林默推开门时，信封正压在门槛内侧。纸面没有署名，只有一道被雨水晕开的墨痕。"
                "他没有立刻去碰。那道墨痕像一枚搁浅多年的指纹，把旧港的潮声重新带回屋里。"
            ),
            memory_tabs=(
                ("压缩前文", "第一章：林默回到雾港，发现旧宅近期有人进入。"),
                ("人物状态", "林默：警惕；目标是查明兄长下落。"),
                ("读者知识", "读者已见过无名人在钟楼投递信件。"),
                ("正典", "旧港钟楼在十二年前火灾后停止公开使用。"),
                ("叙事线索", "CL-04 真实伏笔；CL-07 人工锁定的误导线索。"),
                ("过期依赖", "无。"),
            ),
            style_rules=(
                ("全书声音", "克制的近距离第三人称", "人工锁定"),
                ("人物声音", "林默避免直接承认恐惧", "人工锁定"),
                ("禁用模式", "避免连续使用‘沉默片刻’", "每章 1 次"),
            ),
            audit_findings=(
                ("确定性", "重复动作", "‘抬眼’在本章出现 4 次，规则上限为 2 次。"),
                ("模型", "知识边界", "第二段暗示林默知道寄信人，可能越过当前知识状态。"),
            ),
        )
