from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.project_constitution import (
    ProjectConstitution,
    ProjectConstitutionProposal,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)

_LAYER_NAMES = (
    "shared_creative_rules",
    "agent_only_rules",
    "writer_only_rules",
    "overridable_rules",
    "non_overridable_rules",
)


@dataclass(frozen=True, slots=True)
class LayerDiff:
    layer: str
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    changed_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConstitutionChangePreview:
    base_revision: int
    current_revision: int
    current_matches_base: bool
    layers: tuple[LayerDiff, ...]


class ProjectConstitutionService:
    """get/build/commit facade for the versioned constitution (DCP step 5).

    build only validates and previews; commit requires the author approval
    credential and the expected revision. The backend never lets a prompt or
    proposal change its own program permissions.
    """

    def __init__(self, repository: ProjectConstitutionRepository) -> None:
        self._repository = repository

    def get_project_constitution(self) -> ProjectConstitution | None:
        return self._repository.current()

    def build_proposal(
        self, proposal: ProjectConstitutionProposal
    ) -> ConstitutionChangePreview:
        if not isinstance(proposal, ProjectConstitutionProposal):
            raise TypeError("constitution proposal is invalid")
        current = self._repository.current()
        layers: list[LayerDiff] = []
        for layer in _LAYER_NAMES:
            proposed = {rule.rule_id: rule.text for rule in getattr(proposal, layer)}
            existing = (
                {rule.rule_id: rule.text for rule in getattr(current, layer)}
                if current is not None
                else {}
            )
            added = tuple(sorted(set(proposed) - set(existing)))
            removed = tuple(sorted(set(existing) - set(proposed)))
            changed = tuple(
                sorted(
                    rule_id
                    for rule_id in set(proposed) & set(existing)
                    if proposed[rule_id] != existing[rule_id]
                )
            )
            layers.append(LayerDiff(layer, added, removed, changed))
        return ConstitutionChangePreview(
            base_revision=proposal.base_revision,
            current_revision=current.revision if current is not None else 0,
            current_matches_base=(
                proposal.base_revision == current.revision if current is not None
                else proposal.base_revision == 0
            ),
            layers=tuple(layers),
        )

    def commit(
        self,
        proposal: ProjectConstitutionProposal,
        *,
        approved_by_author: bool,
        expected_revision: int,
    ) -> ProjectConstitution:
        if not isinstance(proposal, ProjectConstitutionProposal):
            raise TypeError("constitution proposal is invalid")
        if not approved_by_author:
            raise ValueError("constitution commit requires author approval")
        if expected_revision < 0:
            raise ValueError("constitution expected revision is invalid")
        return self._repository.save(
            proposal,
            approved_by_author=True,
            expected_revision=expected_revision,
        )
