from __future__ import annotations

import pytest

from ai_novel_studio.domain.generation import AuditPolicy, GenerationProfile
from ai_novel_studio.harness.agent_loop import validate_generation_pairing


def test_quick_requires_minimal() -> None:
    validate_generation_pairing(GenerationProfile.QUICK, AuditPolicy.MINIMAL)


def test_normal_requires_standard() -> None:
    validate_generation_pairing(GenerationProfile.NORMAL, AuditPolicy.STANDARD)


def test_quick_rejects_standard_and_deep() -> None:
    for policy in (AuditPolicy.STANDARD, AuditPolicy.DEEP):
        with pytest.raises(ValueError, match="requires audit policy MINIMAL"):
            validate_generation_pairing(GenerationProfile.QUICK, policy)


def test_normal_rejects_minimal_and_deep() -> None:
    for policy in (AuditPolicy.MINIMAL, AuditPolicy.DEEP):
        with pytest.raises(ValueError, match="requires audit policy STANDARD"):
            validate_generation_pairing(GenerationProfile.NORMAL, policy)
