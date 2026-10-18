"""Translate the writing composer's commands into explicit novel skill requests."""

WRITING_OPERATIONS = frozenset({"重写", "润色", "精简", "扩写", "生成草稿", "续写"})
_ALIASES = dict(
    zip(
        ("rewrite", "polish", "shorten", "expand", "draft", "continue"),
        ("重写", "润色", "精简", "扩写", "生成草稿", "续写"),
        strict=True,
    )
)


def writing_request(text: str) -> tuple[str, str]:
    """Return (operation, prompt); ordinary conversation passes through unchanged."""
    if not text.startswith("/"):
        return "", text
    parts = text[1:].split(maxsplit=1)
    command = parts[0] if parts else ""
    details = parts[1] if len(parts) > 1 else ""
    operation = _ALIASES.get(command, command)
    if operation not in WRITING_OPERATIONS:
        raise ValueError("没有这个指令。输入 / 查看写作操作，或直接用自然语言提问。")
    return operation, (
        f"$novel-edit 请执行“{operation}”。先读取本轮小说上下文和选文；有选文时仅处理选文，"
        "不要扩大到整章。保留作者章要求与既有事实，调用独立正文写作模型生成候选，"
        "不覆盖正式正文。\n作者补充：" + (details.strip() or "无")
    )
