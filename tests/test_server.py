import time

import pytest
from fastapi.testclient import TestClient

from nanovna_tuner.calibration import Calibration
from nanovna_tuner.server import SweepWorker, create_app, impedance, swr

TOKEN = "secret-token"


class FakeDevice:
    """Raw device with a fixed error model; `connected` is the reflection of whatever is attached."""

    name = "Fake"
    raw = True
    min_freq = 50_000
    max_freq = 100_000_000
    max_points = 1024
    connected = complex(0, 0)

    def sweep(self, start, stop, points):
        time.sleep(0.01)
        step = (stop - start) // (points - 1)
        g = self.connected
        return [(start + i * step, 0.1 + 0.6 * g / (1 - 0.2 * g)) for i in range(points)]

    def close(self):
        pass


def wait_for(worker, predicate, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        data = worker.latest()[1]
        if predicate(data):
            return data
        time.sleep(0.01)
    raise AssertionError(f"condition not met, last data: {data}")


@pytest.fixture
def setup(tmp_path):
    device = FakeDevice()
    worker = SweepWorker(lambda: device, 1_000_000, 30_000_000, 51, Calibration(tmp_path / "cal.json"))
    worker.start()
    client = TestClient(create_app(worker, "http://192.0.2.1:8000", TOKEN))
    client.headers["X-Token"] = TOKEN
    return device, worker, client


def test_swr_and_impedance():
    assert swr(0) == 1
    assert swr(1 / 3) == pytest.approx(2)
    assert impedance(0) == 50
    assert impedance(1) is None


def test_token_required(setup):
    _, _, client = setup
    anon = TestClient(client.app)
    assert anon.get("/").status_code == 200
    assert anon.get("/api/sweep").status_code == 401
    assert anon.get("/api/sweep", headers={"X-Token": "wrong"}).status_code == 401
    assert anon.get(f"/qr.svg?t={TOKEN}").status_code == 200
    assert client.get("/api/sweep").status_code == 200


def test_range_limited_to_device(setup):
    _, worker, client = setup
    wait_for(worker, lambda d: d.get("device") == "Fake")
    assert client.post("/api/range", json={"start": 10_000, "stop": 1_000_000}).status_code == 422
    assert client.post("/api/range", json={"start": 1_000_000, "stop": 200_000_000}).status_code == 422
    assert client.post("/api/range", json={"start": 2_000_000, "stop": 1_000_000}).status_code == 422
    assert client.post("/api/range", json={"start": 1_000_000, "stop": 2_000_000}).status_code == 200


def test_calibration_flow(setup):
    device, worker, client = setup
    data = wait_for(worker, lambda d: d.get("cal") is not None)
    assert data["error"].startswith("Calibration needed")

    for std, gamma in (("open", 1), ("short", -1), ("load", 0)):
        device.connected = complex(gamma)
        assert client.post(f"/api/cal/{std}").json() == {"ok": True, "discarded": False}

    device.connected = complex(1 / 3)  # SWR 2, 100 ohm
    data = wait_for(worker, lambda d: d.get("error") is None and d["min_swr"] > 1.5)
    assert data["min_swr"] == pytest.approx(2, abs=0.01)
    assert data["min_z"][0] == pytest.approx(100, abs=0.5)

    assert client.post("/api/cal/clear").status_code == 200
    wait_for(worker, lambda d: (d.get("error") or "").startswith("Calibration needed"))
    assert client.post("/api/cal/bogus").status_code == 404
