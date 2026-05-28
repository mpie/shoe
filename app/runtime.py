from __future__ import annotations

import os
import time


DESKTOP_MODE = os.getenv("DESKTOP_APP", "").casefold() in {"1", "true", "yes", "on"}
last_heartbeat_at = time.monotonic()
