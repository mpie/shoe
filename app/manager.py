"""Holds one SiteMonitor per configured site so they run concurrently."""

from __future__ import annotations

from typing import Any

from app.monitor import SiteMonitor
from app.sites import PROFILES


class MonitorManager:
    def __init__(self) -> None:
        self._monitors: dict[str, SiteMonitor] = {
            key: SiteMonitor(profile) for key, profile in PROFILES.items()
        }

    def get(self, monitor_id: str) -> SiteMonitor:
        monitor = self._monitors.get(monitor_id)
        if monitor is None:
            raise KeyError(monitor_id)
        return monitor

    def snapshot_all(self) -> list[dict[str, Any]]:
        return [self._monitors[key].snapshot() for key in self._monitors]


manager = MonitorManager()
