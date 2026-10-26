# Copyright (C) 2026 Andreas Karpf
# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import io
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .calibration import STANDARDS, Calibration

STATIC = Path(__file__).parent / "static"
MIN_FREQ = 10_000
MAX_FREQ = 3_000_000_000

log = logging.getLogger(__name__)


def load_token(path: Path) -> str:
    """Persisted so bookmarks and scanned links keep working across restarts; delete the file to rotate."""
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(0o600)
    return token


class SweepRange(BaseModel):
    start: int = Field(ge=MIN_FREQ, le=MAX_FREQ)
    stop: int = Field(ge=MIN_FREQ, le=MAX_FREQ)

    @model_validator(mode="after")
    def check_order(self):
        if self.stop <= self.start:
            raise ValueError("stop must be greater than start")
        return self


def swr(gamma: complex) -> float:
    mag = min(abs(gamma), 0.999)
    return (1 + mag) / (1 - mag)


def impedance(gamma: complex, z0: float = 50.0) -> complex | None:
    if abs(1 - gamma) < 1e-9:
        return None
    return z0 * (1 + gamma) / (1 - gamma)


class SweepWorker(threading.Thread):
    """Sweeps the device continuously and keeps the latest result."""

    def __init__(self, connect: Callable, start: int, stop: int, points: int, calibration: Calibration):
        super().__init__(daemon=True)
        self._connect = connect
        self._lock = threading.Lock()
        self._range = (start, stop)
        self._points = points
        self._device_points = points
        self._limits = (MIN_FREQ, MAX_FREQ)
        self._device_name = "device"
        self._cal = calibration
        self._cal_request: dict | None = None
        self._latest: dict = {"error": "Waiting for first sweep…"}
        self._seq = 0

    def set_range(self, start: int, stop: int) -> None:
        with self._lock:
            lo, hi = self._limits
            if start < lo or stop > hi:
                raise ValueError(f"{self._device_name} supports {lo / 1e6:g}–{hi / 1e6:g} MHz")
            self._range = (start, stop)

    def measure_standard(self, standard: str) -> dict:
        """Blocks until the next sweep has captured the standard."""
        req = {"standard": standard, "done": threading.Event(), "error": None, "discarded": False}
        with self._lock:
            self._cal_request = req
        if not req["done"].wait(120):
            req["error"] = "Timed out waiting for a sweep"
        return req

    def clear_calibration(self) -> None:
        with self._lock:
            self._cal.clear()

    def latest(self) -> tuple[int, dict]:
        with self._lock:
            return self._seq, self._latest

    def _publish(self, data: dict) -> None:
        with self._lock:
            self._latest = data
            self._seq += 1

    def _on_connect(self, device) -> None:
        log.info("Connected to %s", device.name)
        with self._lock:
            lo, hi = device.min_freq, device.max_freq
            self._limits = (lo, hi)
            self._device_name = device.name
            start, stop = self._range
            clamped = (max(start, lo), min(stop, hi))
            if clamped[1] <= clamped[0]:
                clamped = (lo, hi)
            if clamped != (start, stop):
                log.warning("Range limited to %s: %g–%g MHz", device.name, clamped[0] / 1e6, clamped[1] / 1e6)
                self._range = clamped
            self._device_points = min(self._points, device.max_points)
            if self._device_points != self._points:
                log.warning("%s supports at most %d points", device.name, device.max_points)

    def run(self) -> None:
        device = None
        last_error = None
        while True:
            cal_request = None
            try:
                if device is None:
                    device = self._connect()
                    self._on_connect(device)
                with self._lock:
                    start, stop = self._range
                    # taken before sweeping so the standard is already connected during the sweep
                    cal_request, self._cal_request = self._cal_request, None
                data = device.sweep(start, stop, self._device_points)
            except Exception as e:
                if str(e) != last_error:
                    log.warning("%s (retrying every 2 s)", e)
                    last_error = str(e)
                with self._lock:
                    start, stop = self._range
                self._publish({"error": str(e), "start": start, "stop": stop})
                if cal_request:
                    cal_request["error"] = str(e)
                    cal_request["done"].set()
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
                    device = None
                time.sleep(2)
                continue
            last_error = None

            freqs = [f for f, _ in data]
            gammas = [g for _, g in data]
            info = {
                "start": start,
                "stop": stop,
                "device": device.name,
                "limits": {"min": device.min_freq, "max": device.max_freq},
            }
            if cal_request:
                if device.raw:
                    with self._lock:
                        cal_request["discarded"] = self._cal.measure(cal_request["standard"], freqs, gammas)
                else:
                    cal_request["error"] = f"{device.name} is calibrated on the device itself"
                cal_request["done"].set()
            if device.raw:
                cal_error = None
                with self._lock:
                    info["cal"] = self._cal.status()
                    try:
                        gammas = self._cal.apply(freqs, gammas)
                    except RuntimeError as e:
                        cal_error = str(e)
                if cal_error:
                    self._publish({"error": cal_error, **info})
                    continue

            swrs = [round(swr(g), 3) for g in gammas]
            i = min(range(len(swrs)), key=swrs.__getitem__)
            z = impedance(gammas[i])
            self._publish({
                "error": None,
                "timestamp": time.time(),
                **info,
                "freqs": freqs,
                "swr": swrs,
                "min_index": i,
                "min_freq": freqs[i],
                "min_swr": swrs[i],
                "min_z": [round(z.real, 1), round(z.imag, 1)] if z is not None else None,
            })


def create_app(worker: SweepWorker, lan_url: str, token: str) -> FastAPI:
    buf = io.BytesIO()
    segno.make(f"{lan_url}/?t={token}", error="m").save(buf, kind="svg", scale=4, border=2)
    qr_svg = buf.getvalue()

    def require_token(request: Request) -> None:
        if request.client is not None and request.client.host in ("127.0.0.1", "::1"):
            return
        given = request.headers.get("x-token") or request.query_params.get("t") or ""
        if not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "Access denied - scan the QR code shown on the computer running the app")

    app = FastAPI(title="NanoVNA Tuner", docs_url=None, redoc_url=None, openapi_url=None)
    protected = [Depends(require_token)]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/info", dependencies=protected)
    def info():
        return {"url": lan_url}

    @app.get("/qr.svg", dependencies=protected)
    def qr():
        return Response(qr_svg, media_type="image/svg+xml")

    @app.get("/api/sweep", dependencies=protected)
    def sweep():
        return worker.latest()[1]

    @app.get("/api/stream", dependencies=protected)
    async def stream(request: Request):
        async def events():
            seq, idle = -1, 0.0
            while not await request.is_disconnected():
                current, data = worker.latest()
                if current != seq:
                    seq, idle = current, 0.0
                    yield f"data: {json.dumps(data)}\n\n"
                elif idle >= 15:
                    idle = 0.0
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.2)
                idle += 0.2

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/range", dependencies=protected)
    def set_range(r: SweepRange):
        try:
            worker.set_range(r.start, r.stop)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return r

    @app.post("/api/cal/clear", dependencies=protected)
    def clear_calibration():
        worker.clear_calibration()
        return {"ok": True}

    @app.post("/api/cal/{standard}", dependencies=protected)
    def calibrate(standard: str):
        if standard not in STANDARDS:
            raise HTTPException(404, "Unknown standard")
        result = worker.measure_standard(standard)
        if result["error"]:
            raise HTTPException(409, result["error"])
        return {"ok": True, "discarded": result["discarded"]}

    return app
