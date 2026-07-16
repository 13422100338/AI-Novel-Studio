"""UI feature gates for optional or retired workflows.

The underlying services and persisted records intentionally remain available for
future migration and rollback.  These flags only control what users can start
from the current interface.
"""

AGENT_TOOLS_ENABLED = True
LEGACY_STYLE_AUTOMATION_VISIBLE = False
