from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.manager import manager
from app.monitor import DEFAULT_INTERVAL_SECONDS
from app import runtime


if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Sneaker Multi-Site Monitor")


class StartMonitorRequest(BaseModel):
    search_text: str | None = Field(default=None, alias="searchText")
    target_url: str | None = Field(default=None, alias="targetUrl")
    interval_seconds: int = Field(default=DEFAULT_INTERVAL_SECONDS, alias="intervalSeconds", ge=5)
    size: str | None = None


def _monitor_or_404(monitor_id: str):
    try:
        return manager.get(monitor_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown monitor: {monitor_id}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    return {"monitors": manager.snapshot_all()}


@app.get("/api/status/{monitor_id}")
def status_one(monitor_id: str) -> dict:
    return _monitor_or_404(monitor_id).snapshot()


@app.post("/api/start/{monitor_id}")
async def start(monitor_id: str, request: StartMonitorRequest) -> dict:
    monitor = _monitor_or_404(monitor_id)
    return await monitor.start(
        search_text=request.search_text,
        target_url=request.target_url,
        interval_seconds=request.interval_seconds,
        size=request.size,
    )


@app.post("/api/stop/{monitor_id}")
async def stop(monitor_id: str) -> dict:
    return await _monitor_or_404(monitor_id).stop()


@app.post("/api/logs/clear/{monitor_id}")
def clear_logs(monitor_id: str) -> dict:
    return _monitor_or_404(monitor_id).clear_logs()


@app.get("/api/runtime")
def runtime_status() -> dict:
    return {"desktop": runtime.DESKTOP_MODE}


@app.post("/api/heartbeat")
def heartbeat() -> dict:
    if not runtime.DESKTOP_MODE:
        raise HTTPException(status_code=404)

    runtime.last_heartbeat_at = time.monotonic()
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
