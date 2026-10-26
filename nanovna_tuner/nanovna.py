import random
import time
from struct import pack, unpack_from

import serial
from serial.tools import list_ports

# STM32 virtual COM port used by NanoVNA / NanoVNA-H / NanoVNA-H4
NANOVNA_VID = 0x0483
NANOVNA_PID = 0x5740
# NanoVNA V2 / V2 Plus4 / LiteVNA
V2_VID = 0x04B4
V2_PID = 0x0008
PROMPT = b"ch> "


def open_device(port: str | None = None):
    ports = list_ports.comports()
    if port:
        info = next((p for p in ports if p.device == port), None)
    else:
        known = {(NANOVNA_VID, NANOVNA_PID), (V2_VID, V2_PID)}
        info = next((p for p in ports if (p.vid, p.pid) in known), None)
        if info is None:
            raise RuntimeError("NanoVNA not found - is it plugged in and switched on?")
    if info is not None and (info.vid, info.pid) == (V2_VID, V2_PID):
        return NanoVNAV2(info.device)
    return NanoVNA(port or info.device)


class NanoVNA:
    """Text shell protocol of NanoVNA / NanoVNA-H / NanoVNA-H4 firmware."""

    name = "NanoVNA"
    raw = False
    min_freq = 10_000
    max_freq = 1_500_000_000
    max_points = 401

    def __init__(self, port: str):
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


class NanoVNAV2:
    """Binary register protocol of NanoVNA V2 / V2 Plus4 / LiteVNA.

    USB data is uncalibrated (raw = True); the on-screen calibration is not applied.
    """

    name = "NanoVNA V2"
    raw = True
    min_freq = 50_000
    max_freq = 3_000_000_000
    max_points = 1024

    def __init__(self, port: str):
        self.ser = serial.Serial(port, 115200, timeout=2)
        # 8 NOPs reset the protocol parser to a known state
        self.ser.write(bytes(8))
        time.sleep(0.05)
        self.ser.reset_input_buffer()
        self.ser.write(bytes([0x0D]))
        if self.ser.read(1) != b"2":
            self.ser.close()
            raise RuntimeError(f"{port} did not identify as a NanoVNA V2")
        self.ser.write(bytes([0x10, 0xF3]))
        if self.ser.read(1) == b"\xff":
            self.ser.close()
            raise RuntimeError("NanoVNA V2 is in firmware-update (DFU) mode - restart it normally")

    def sweep(self, start: int, stop: int, points: int) -> list[tuple[int, complex]]:
        step = (stop - start) // (points - 1)
        self.ser.write(
            pack("<BBQ", 0x23, 0x00, start)
            + pack("<BBQ", 0x23, 0x10, step)
            + pack("<BBH", 0x21, 0x20, points)
            + pack("<BBH", 0x21, 0x22, 1)
        )
        time.sleep(0.05)
        self.ser.write(pack("<BBB", 0x20, 0x30, 0))  # clear values FIFO
        time.sleep(0.05)

        values: list[complex | None] = [None] * points
        remaining = points
        while remaining:
            n = min(255, remaining)
            self.ser.timeout = n * 0.05 + 1
            self.ser.write(pack("<BBB", 0x18, 0x30, n))
            buf = self.ser.read(n * 32)
            if len(buf) != n * 32:
                raise TimeoutError("No sweep data from NanoVNA V2")
            for k in range(n):
                fwd_re, fwd_im, rev_re, rev_im, _, _, idx = unpack_from("<iiiiiiH", buf, k * 32)
                if 0 <= idx < points:
                    values[idx] = complex(rev_re, rev_im) / complex(fwd_re, fwd_im)
            remaining -= n
        if None in values:
            raise RuntimeError("Incomplete sweep from NanoVNA V2")
        return [(start + i * step, v) for i, v in enumerate(values)]

    def close(self) -> None:
        self.ser.close()


class SimulatedNanoVNA:
    """Fake series-resonant antenna for testing without hardware."""

    name = "Simulator"
    raw = False
    min_freq = 10_000
    max_freq = 3_000_000_000
    max_points = 1024

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
