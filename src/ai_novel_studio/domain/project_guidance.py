from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class ProjectGuidance:
    project_id: str
    highest_system_prompt: str
    revision: int
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.project_id)
        if self.revision < 0:
            raise ValueError("项目最高提示修订号不能为负数")
