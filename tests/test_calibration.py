# Copyright (C) 2026 Andreas Karpf
# SPDX-License-Identifier: GPL-3.0-or-later
import cmath

import pytest

from nanovna_tuner.calibration import Calibration

FREQS = list(range(1_000_000, 30_000_001, 290_000))


def error_model(f):
    """Arbitrary smooth directivity, source match and reflection tracking."""
    return 0.1 * cmath.exp(1j * f / 1e7), 0.2 * cmath.exp(-1j * f / 2e7), 0.5 * cmath.exp(-2j * f / 1e7)


def measured(f, gamma):
    e00, e11, t = error_model(f)
    return e00 + t * gamma / (1 - e11 * gamma)


def calibrate(cal, freqs=FREQS):
    for name, gamma in (("open", 1), ("short", -1), ("load", 0)):
        cal.measure(name, freqs, [measured(f, gamma) for f in freqs])


def test_recovers_true_reflection(tmp_path):
    cal = Calibration(tmp_path / "cal.json")
    calibrate(cal)
    assert cal.valid
    dut = complex(0.3, -0.2)
    freqs = [14_000_000, 14_150_000, 14_300_000]  # between calibration points
    corrected = cal.apply(freqs, [measured(f, dut) for f in freqs])
    assert all(abs(g - dut) < 1e-3 for g in corrected)


def test_persists_and_clears(tmp_path):
    path = tmp_path / "cal.json"
    calibrate(Calibration(path))
    reloaded = Calibration(path)
    assert reloaded.valid
    assert reloaded.status()["created"] is not None
    reloaded.clear()
    assert not reloaded.valid
    assert not path.exists()


def test_range_change_discards_partial_standards(tmp_path):
    cal = Calibration(tmp_path / "cal.json")
    assert cal.measure("open", FREQS, [1] * len(FREQS)) is False
    other = [f + 1000 for f in FREQS]
    assert cal.measure("short", other, [-1] * len(other)) is True
    assert cal.status()["measured"] == ["short"]


def test_rejects_sweep_outside_calibrated_range(tmp_path):
    cal = Calibration(tmp_path / "cal.json")
    calibrate(cal)
    with pytest.raises(RuntimeError, match="outside the calibrated range"):
        cal.apply([500_000, 1_000_000], [0, 0])


def test_uncalibrated_apply_raises(tmp_path):
    with pytest.raises(RuntimeError, match="Calibration needed"):
        Calibration(tmp_path / "cal.json").apply(FREQS, [0] * len(FREQS))
