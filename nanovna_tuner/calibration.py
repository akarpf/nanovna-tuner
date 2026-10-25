import bisect
import json
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
        if path.exists():
            d = json.loads(path.read_text())
            self.freqs = d["freqs"]
            self.e00, self.e11, self.t = ([complex(*v) for v in d[k]] for k in ("e00", "e11", "t"))

    @property
    def valid(self) -> bool:
        return bool(self.freqs)

    def status(self) -> dict:
        return {
            "valid": self.valid,
            "measured": [s for s in STANDARDS if s in self.measured],
            "start": self.freqs[0] if self.valid else None,
            "stop": self.freqs[-1] if self.valid else None,
        }

    def measure(self, standard: str, freqs: list[int], values: list[complex]) -> None:
        # standards from a different sweep range can't be combined
        if any(f != freqs for f, _ in self.measured.values()):
            self.measured.clear()
        self.measured[standard] = (freqs, values)
        if len(self.measured) == len(STANDARDS):
            self._solve()

    def _solve(self) -> None:
        freqs = self.measured["open"][0]
        e00, e11, t = [], [], []
        for o, s, l in zip(*(self.measured[n][1] for n in STANDARDS)):
            a = (o + s - 2 * l) / (o - s)
            e00.append(l)
            e11.append(a)
            t.append((o - l) * (1 - a))
        self.freqs, self.e00, self.e11, self.t = freqs, e00, e11, t
        self.measured.clear()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "freqs": freqs,
            **{k: [[v.real, v.imag] for v in getattr(self, k)] for k in ("e00", "e11", "t")},
        }))

    def apply(self, freqs: list[int], raw: list[complex]) -> list[complex]:
        if not self.valid:
            raise RuntimeError("Calibration needed: measure Open, Short and Load")
        lo, hi = self.freqs[0], self.freqs[-1]
        if freqs[0] < lo or freqs[-1] > hi:
            raise RuntimeError(
                f"Sweep is outside the calibrated range {lo / 1e6:.3f}–{hi / 1e6:.3f} MHz - recalibrate"
            )
        out = []
        for f, m in zip(freqs, raw):
            d = m - _interp(self.freqs, self.e00, f)
            out.append(d / (_interp(self.freqs, self.t, f) + _interp(self.freqs, self.e11, f) * d))
        return out
