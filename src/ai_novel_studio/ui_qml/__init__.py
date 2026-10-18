"""Frontend Wave F1: QML application shell, design tokens, and mock facade.

This package is intentionally additive. It must not import ``ai_novel_studio.ui``,
``ai_novel_studio.domain``, or ``ai_novel_studio.infrastructure`` directly. Since
Frontend Wave F2 it consumes the read-only application service
``ProjectWorkspaceService`` through the facade; it never writes project files,
databases, or model state, and never changes backend interfaces.
Frontend Wave F1 work lives exclusively in this package, ``tests/ui_qml``,
``docs/frontend``, and the dedicated screenshot script.
"""
