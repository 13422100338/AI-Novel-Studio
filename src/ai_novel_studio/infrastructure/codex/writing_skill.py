"""The app-owned writing skill; never resolve arbitrary user-supplied paths."""

from pathlib import Path

WRITING_SKILL_ROOT = Path(__file__).resolve().parent / "skills"
WRITING_SKILL_PATH = WRITING_SKILL_ROOT / "novel-edit" / "SKILL.md"


def session_skill_path(cwd: Path) -> Path:
    return cwd / ".agents" / "skills" / "studio-novel-edit-v2" / "SKILL.md"


def prepare_writing_skill(cwd: Path) -> Path:
    """Stage the packaged skill in the app-owned Codex workspace, never the novel."""
    path = session_skill_path(cwd)
    if not path.resolve().is_relative_to(cwd.resolve()):
        raise ValueError("小说编辑技能目录异常，请检查程序工作目录")
    content = WRITING_SKILL_PATH.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("小说编辑技能副本已被修改，未覆盖；请检查程序工作目录") from None
    return path


def writing_skill_input(message: str, cwd: Path) -> dict[str, object] | None:
    parts = message.split(maxsplit=1)
    if not parts or parts[0] != "$novel-edit":
        return None
    path = session_skill_path(cwd)
    if not path.is_file() or path.read_bytes() != WRITING_SKILL_PATH.read_bytes():
        raise ValueError("小说编辑技能文件缺失，请修复程序后重试")
    return {"type": "skill", "name": "novel-edit", "path": str(path)}
