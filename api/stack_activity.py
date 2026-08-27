"""Track API activity so the host can stop idle Docker stacks."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_FILE = Path(os.getenv("STACK_ACTIVITY_FILE", "data/.last_api_activity"))


def touch_stack_activity() -> None:
    """Record UTC timestamp of the last non-health API request."""
    try:
        ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVITY_FILE.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
    except OSError:
        pass
