from struct import pack, unpack_from

import pytest

from nanovna_tuner import nanovna


class FakeTextSerial:
    """Mimics the NanoVNA-H shell: echoes the command, prints the output, ends with the prompt."""

    def __init__(self, *args, **kwargs):
        self.buf = b""

    def reset_input_buffer(self):
        pass

    def write(self, data):
        cmd = data.decode().strip()
        out = cmd + "\r\n"
        if cmd.startswith("scan"):
            _, start, stop, points, _ = cmd.split()
            start, stop, points = int(start), int(stop), int(points)
            for i in range(points):
                f = start + (stop - start) * i // (points - 1)
                out += f"{f} {i / 100:.6f} {-i / 200:.6f}\r\n"
        self.buf = (out + "ch> ").encode()

    def read_until(self, terminator):
        data, self.buf = self.buf, b""
        return data

    def close(self):
        pass


class FakeV2Serial:
    """Minimal register-protocol emulation of a NanoVNA V2."""

    first_index = 3  # FIFO does not start at index 0, like the real device mid-sweep

    def __init__(self, *args, **kwargs):
        self.out = bytearray()
        self.timeout = 2
        self.points = 0

    def reset_input_buffer(self):
        self.out.clear()

    def write(self, data):
        i = 0
        while i < len(data):
            op = data[i]
            if op == 0x00:
                i += 1
            elif op == 0x0D:
                self.out += b"2"
                i += 1
            elif op == 0x10:
                self.out += b"\x01"
                i += 2
            elif op == 0x20:
                i += 3
            elif op == 0x21:
                if data[i + 1] == 0x20:
                    self.points = unpack_from("<H", data, i + 2)[0]
                i += 4
            elif op == 0x23:
                i += 10
            elif op == 0x18:
                for k in range(data[i + 2]):
                    idx = (self.first_index + k) % self.points
                    # gamma = idx / 1000 with forward wave 1000
                    self.out += pack("<iiiiiiH6x", 1000, 0, idx, 0, 0, 0, idx)
                i += 3
            else:
                raise AssertionError(f"unexpected opcode {op:#x}")

    def read(self, n):
        data = bytes(self.out[:n])
        del self.out[:n]
        return data

    def close(self):
        pass


def test_text_protocol_sweep(monkeypatch):
    monkeypatch.setattr(nanovna.serial, "Serial", FakeTextSerial)
    dev = nanovna.NanoVNA("/dev/fake")
    data = dev.sweep(1_000_000, 2_000_000, 11)
    assert len(data) == 11
    assert data[0] == (1_000_000, complex(0, 0))
    assert data[-1] == (2_000_000, complex(0.1, -0.05))
    assert not dev.raw


def test_v2_protocol_sweep_reorders_by_index(monkeypatch):
    monkeypatch.setattr(nanovna.serial, "Serial", FakeV2Serial)
    dev = nanovna.NanoVNAV2("/dev/fake")
    data = dev.sweep(1_000_000, 2_000_000, 11)
    assert [f for f, _ in data] == [1_000_000 + i * 100_000 for i in range(11)]
    assert [round(g.real, 3) for _, g in data] == [i / 1000 for i in range(11)]
    assert dev.raw


def test_v2_rejects_dfu_mode(monkeypatch):
    class Dfu(FakeV2Serial):
        def write(self, data):
            if data == bytes([0x10, 0xF3]):
                self.out += b"\xff"
            else:
                super().write(data)

    monkeypatch.setattr(nanovna.serial, "Serial", Dfu)
    with pytest.raises(RuntimeError, match="DFU"):
        nanovna.NanoVNAV2("/dev/fake")


def test_open_device_not_found(monkeypatch):
    monkeypatch.setattr(nanovna.list_ports, "comports", lambda: [])
    with pytest.raises(RuntimeError, match="not found"):
        nanovna.open_device()
