# Copyright (C) 2026 Andreas Karpf
# SPDX-License-Identifier: GPL-3.0-or-later
import bisect
import json
import time
from pathlib import Path

STANDARDS = ("open", "short", "load")


def _interp(xs: list[int], ys: list[complex], x: float) -> complex:
    i = bisect.bisect_left(xs, x)
    if i < len(xs) and xs[i] == x:
        return ys[i]
    t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
    return ys[i - 1] + (ys[i] - ys[i - 1]) * t


class Calibration:
    """One-port Open/Short/Load calibration with ideal standards, persisted to disk."""

    def __init__(self, path: Path):
        self.path = path
        self.measured: dict[str, tuple[list[int], list[complex]]] = {}
        self.freqs: list[int] = []
        self.e00: list[complex] = []
        self.e11: list[complex] = []
        self.t: list[complex] = []
        self.created: float | None = None
        if path.exists():
            d = json.loads(path.read_text())
            self.freqs = d["freqs"]
            self.e00, self.e11, self.t = ([complex(*v) for v in d[k]] for k in ("e00", "e11", "t"))
            self.created = d.get("created")

    @property
    def valid(self) -> bool:
        return bool(self.freqs)

    def status(self) -> dict:
        return {
            "valid": self.valid,
            "measured": [s for s in STANDARDS if s in self.measured],
            "start": self.freqs[0] if self.valid else None,
            "stop": self.freqs[-1] if self.valid else None,
            "created": self.created,
        }

    def clear(self) -> None:
        self.measured.clear()
        self.freqs, self.e00, self.e11, self.t = [], [], [], []
        self.created = None
        self.path.unlink(missing_ok=True)

    def measure(self, standard: str, freqs: list[int], values: list[complex]) -> bool:
        """Returns True if previously measured standards were discarded because the range changed."""
        discarded = any(f != freqs for f, _ in self.measured.values())
        if discarded:
            self.measured.clear()
        self.measured[standard] = (freqs, values)
        if len(self.measured) == len(STANDARDS):
            self._solve()
        return discarded

    def _solve(self) -> None:
        freqs = self.measured["open"][0]
        e00, e11, t = [], [], []
        for open_, short, load in zip(*(self.measured[n][1] for n in STANDARDS), strict=True):
            a = (open_ + short - 2 * load) / (open_ - short)
            e00.append(load)
            e11.append(a)
            t.append((open_ - load) * (1 - a))
        self.freqs, self.e00, self.e11, self.t = freqs, e00, e11, t
        self.created = time.time()
        self.measured.clear()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "freqs": freqs,
                    "created": self.created,
                    **{k: [[v.real, v.imag] for v in getattr(self, k)] for k in ("e00", "e11", "t")},
                }
            )
        )

    def apply(self, freqs: list[int], raw: list[complex]) -> list[complex]:
        if not self.valid:
            raise RuntimeError("Calibration needed: measure Open, Short and Load")
        lo, hi = self.freqs[0], self.freqs[-1]
        if freqs[0] < lo or freqs[-1] > hi:
            raise RuntimeError(f"Sweep is outside the calibrated range {lo / 1e6:.3f}–{hi / 1e6:.3f} MHz - recalibrate")
        out = []
        for f, m in zip(freqs, raw, strict=True):
            d = m - _interp(self.freqs, self.e00, f)
            out.append(d / (_interp(self.freqs, self.t, f) + _interp(self.freqs, self.e11, f) * d))
        return out
