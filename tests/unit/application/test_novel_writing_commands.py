import pytest

from ai_novel_studio.application.novel_writing_commands import writing_request
from ai_novel_studio.infrastructure.codex.writing_skill import (
    prepare_writing_skill,
    writing_skill_input,
)


@pytest.mark.parametrize("command", ["/润色", "/polish", "/polish\n让语言自然一些"])
def test_writing_command_uses_native_skill(command, tmp_path):
    path = prepare_writing_skill(tmp_path)
    operation, request = writing_request(command)
    assert operation == "润色"
    assert writing_skill_input(request, tmp_path) == {
        "type": "skill",
        "name": "novel-edit",
        "path": str(path),
    }


def test_regular_messages_are_unchanged_and_unknown_commands_fail(tmp_path):
    assert writing_request("帮我看看这段") == ("", "帮我看看这段")
    assert writing_skill_input("$other-skill 做点事", tmp_path) is None
    with pytest.raises(ValueError):
        writing_request("/unknown")


def test_skill_copy_never_overwrites_an_existing_modified_file(tmp_path):
    path = prepare_writing_skill(tmp_path)
    path.write_text("a manually edited skill", encoding="utf-8")
    with pytest.raises(ValueError, match="未覆盖"):
        prepare_writing_skill(tmp_path)
    assert path.read_text(encoding="utf-8") == "a manually edited skill"


def test_new_skill_version_coexists_with_old_workspace_copy(tmp_path):
    old_path = tmp_path / ".agents" / "skills" / "studio-novel-edit-v1" / "SKILL.md"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"previous app-owned writing skill")
    path = prepare_writing_skill(tmp_path)
    assert path != old_path
    assert old_path.read_bytes() == b"previous app-owned writing skill"
    content = path.read_text(encoding="utf-8")
    assert (
        "完整大纲" in content and "related_refs" in content and "AWAITING_CONFIRMATION" in content
    )
