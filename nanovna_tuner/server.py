import io
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

import segno
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator

from .calibration import STANDARDS, Calibration

STATIC = Path(__file__).parent / "static"
MIN_FREQ = 10_000
MAX_FREQ = 3_000_000_000

log = logging.getLogger(__name__)


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


class SweepWorker(threading.Thread):
    """Sweeps the device continuously and keeps the latest result."""

    def __init__(self, connect: Callable, start: int, stop: int, points: int, calibration: Calibration):
        super().__init__(daemon=True)
        self._connect = connect
        self._lock = threading.Lock()
        self._range = (start, stop)
        self._points = points
        self._cal = calibration
        self._cal_request: dict | None = None
        self._latest: dict = {"error": "Waiting for first sweep…"}

    def set_range(self, start: int, stop: int) -> None:
        with self._lock:
            self._range = (start, stop)

    def measure_standard(self, standard: str) -> str | None:
        """Blocks until the next sweep has captured the standard; returns an error or None."""
        req = {"standard": standard, "done": threading.Event(), "error": None}
        with self._lock:
            self._cal_request = req
        if not req["done"].wait(120):
            return "Timed out waiting for a sweep"
        return req["error"]

    def latest(self) -> dict:
        with self._lock:
            return self._latest

    def _publish(self, data: dict) -> None:
        with self._lock:
            self._latest = data

    def run(self) -> None:
        device = None
        last_error = None
        while True:
            with self._lock:
                start, stop = self._range
                # taken before sweeping so the standard is already connected during the sweep
                cal_request, self._cal_request = self._cal_request, None
            try:
                if device is None:
                    device = self._connect()
                    log.info("Connected to %s", device.name)
                data = device.sweep(start, stop, self._points)
            except Exception as e:
                if str(e) != last_error:
                    log.warning("%s (retrying every 2 s)", e)
                    last_error = str(e)
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
            info = {"start": start, "stop": stop, "device": device.name}
            if cal_request:
                if device.raw:
                    with self._lock:
                        self._cal.measure(cal_request["standard"], freqs, gammas)
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
            self._publish({
                "error": None,
                "timestamp": time.time(),
                **info,
                "freqs": freqs,
                "swr": swrs,
                "min_index": i,
                "min_freq": freqs[i],
                "min_swr": swrs[i],
            })


def create_app(worker: SweepWorker, lan_url: str) -> FastAPI:
    app = FastAPI(title="NanoVNA Tuner")
    buf = io.BytesIO()
    segno.make(lan_url, error="m").save(buf, kind="svg", scale=4, border=2)
    qr_svg = buf.getvalue()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/info")
    def info():
        return {"url": lan_url}

    @app.get("/qr.svg")
    def qr():
        return Response(qr_svg, media_type="image/svg+xml")

    @app.get("/api/sweep")
    def sweep():
        return worker.latest()

    @app.post("/api/range")
    def set_range(r: SweepRange):
        worker.set_range(r.start, r.stop)
        return r

    @app.post("/api/cal/{standard}")
    def calibrate(standard: str):
        if standard not in STANDARDS:
            raise HTTPException(404, "Unknown standard")
        error = worker.measure_standard(standard)
        if error:
            raise HTTPException(409, error)
        return {"ok": True}

    return app
