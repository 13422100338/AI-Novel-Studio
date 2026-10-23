from __future__ import annotations

import os

# UI tests exercise widget behavior, not the native Windows compositor. Running Qt in
# offscreen mode prevents test windows and COM teardown errors from leaking into the
# user's desktop while preserving pytest-qt event processing.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    # Native Windows control styles need real window handles, which the
    # offscreen platform does not supply. Keep headless tests deterministic.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
