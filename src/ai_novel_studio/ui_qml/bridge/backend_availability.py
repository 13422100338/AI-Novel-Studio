"""Backend availability probe for the standalone frontend.

The standalone repository contains no backend packages. The facade and its
ports degrade to Mock mode when the backend is absent and lazily import backend
services when present. No backend code is copied into this repository.
"""

from __future__ import annotations

try:  # pragma: no cover - depends on the host repository
    from ai_novel_studio.application.project_workspace_service import (  # noqa: F401
        ProjectWorkspaceService,
    )

    BACKEND_AVAILABLE = True
except ImportError:  # pragma: no cover
    BACKEND_AVAILABLE = False
