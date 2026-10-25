import random
import time

import serial
from serial.tools import list_ports

# STM32 virtual COM port used by NanoVNA / NanoVNA-H / NanoVNA-H4
NANOVNA_VID = 0x0483
NANOVNA_PID = 0x5740
PROMPT = b"ch> "


def find_port() -> str | None:
    for p in list_ports.comports():
        if p.vid == NANOVNA_VID and p.pid == NANOVNA_PID:
            return p.device
    return None


class NanoVNA:
    """Text shell protocol of NanoVNA / NanoVNA-H / NanoVNA-H4 firmware."""

    def __init__(self, port: str | None = None):
        port = port or find_port()
        if not port:
            raise RuntimeError("NanoVNA not found - is it plugged in and switched on?")
        self.ser = serial.Serial(port, 115200, timeout=15)
        self._command("")

    def _command(self, cmd: str) -> list[str]:
        self.ser.reset_input_buffer()
        self.ser.write(cmd.encode() + b"\r")
        data = self.ser.read_until(PROMPT)
        if not data.endswith(PROMPT):
            raise TimeoutError(f"No response from NanoVNA to {cmd!r}")
        lines = data[: -len(PROMPT)].decode(errors="replace").splitlines()
        # first line is the echoed command
        return [line.strip() for line in lines[1:] if line.strip()]

    def sweep(self, start: int, stop: int, points: int) -> list[tuple[int, complex]]:
        # outmask 3 = frequency + S11 (re, im)
        result = []
        for line in self._command(f"scan {start} {stop} {points} 3"):
            parts = line.split()
            if len(parts) != 3:
                continue
            freq, re, im = parts
            result.append((int(freq), complex(float(re), float(im))))
        if not result:
            raise RuntimeError("NanoVNA returned no scan data")
        return result

    def close(self) -> None:
        self.ser.close()


class SimulatedNanoVNA:
    """Fake series-resonant antenna for testing without hardware."""

    def __init__(self, resonance_hz: float = 14_150_000, r: float = 58.0, q: float = 60.0):
        self.resonance_hz = resonance_hz
        self.r = r
        self.q = q

    def sweep(self, start: int, stop: int, points: int) -> list[tuple[int, complex]]:
        time.sleep(0.5)
        f0 = self.resonance_hz * (1 + random.uniform(-0.001, 0.001))
        result = []
        for i in range(points):
            f = start + (stop - start) * i / (points - 1)
            z = complex(self.r, self.r * self.q * (f / f0 - f0 / f))
            result.append((int(f), (z - 50) / (z + 50)))
        return result

    def close(self) -> None:
        pass
