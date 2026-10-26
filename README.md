# nanovna-tuner

Live NanoVNA antenna SWR measurements served over the local Wi‑Fi to any browser/phone: frequency of minimum SWR, the SWR value, the SWR < 2 bandwidth, the impedance at the minimum and the SWR curve. The page updates live after every sweep.

## Supported devices

| Device | Calibration |
|---|---|
| NanoVNA / NanoVNA‑H / NanoVNA‑H4 | done on the device |
| NanoVNA V2 (SAA‑2 / SAA‑2N) / V2 Plus4 / LiteVNA | done in the app (the V2 family sends uncalibrated data over USB) |

The model is detected automatically. The NanoVNA can be plugged in (or re-plugged) at any time; the app retries every 2 s and reconnects.

## Installation

**Standalone executable (no Python needed):** download the file for your system from the [Releases page](https://github.com/akarpf/nanovna-tuner/releases) and run it from a terminal (options below).

- **macOS:** the file is not signed by Apple. Allow it once with `xattr -d com.apple.quarantine nanovna-tuner-macos-arm64 && chmod +x nanovna-tuner-macos-arm64`.
- **Windows:** allow network access when the firewall asks, otherwise the phone cannot connect.
- **Linux:** `chmod +x nanovna-tuner-linux-x64`; your user needs access to the serial port: `sudo usermod -aG dialout $USER`, then log out and in again.

The executable unpacks itself on start, so it takes a few seconds until the addresses appear.

**With uv:** `uv tool install git+https://github.com/akarpf/nanovna-tuner`, then run `nanovna-tuner`. For the tray icon install with `uv tool install "nanovna-tuner[tray] @ git+https://github.com/akarpf/nanovna-tuner"` instead.

**From source:** clone the repository and use `uv run python -m nanovna_tuner` as shown below.

## Usage

Requires [uv](https://docs.astral.sh/uv/). Plug in the NanoVNA, switch it on, then:

```sh
uv run python -m nanovna_tuner                 # auto-detects the NanoVNA
uv run python -m nanovna_tuner --simulate      # no hardware, simulated 20 m antenna
uv run python -m nanovna_tuner --start 13.5 --stop 14.8 --points 201
```

The terminal prints two addresses:

- `http://localhost:8000` – open on the computer running the app. The **QR** button shows a code for the phone.
- `http://<ip>:8000/?t=<token>` – the phone link (same as the QR code).

On the page, use the band selector or Start/Stop + **Apply** to set the range, and **Zoom to min** to narrow the sweep around the resonance. Stop the app with Ctrl+C.

## Command-line options

| Option | Default | Description |
|---|---|---|
| `--port PORT` | auto-detect | Serial port of the NanoVNA, e.g. `/dev/cu.usbmodemDEMO1` (macOS), `COM3` (Windows), `/dev/ttyACM0` (Linux). Only needed if auto-detection picks the wrong device. List ports with `ls /dev/cu.usbmodem*` (macOS). |
| `--simulate` | off | Use a simulated antenna (resonance near 14.15 MHz) instead of a NanoVNA. For testing without hardware. |
| `--start MHZ` | `1` | Start frequency of the sweep in MHz at program start. Can be changed later on the page. |
| `--stop MHZ` | `30` | Stop frequency of the sweep in MHz at program start. Can be changed later on the page. |
| `--points N` | `101` | Measurement points per sweep (11–1024). More points give a finer curve and a more exact minimum, but each sweep takes longer (NanoVNA V2: about 27 ms per point, so 101 points ≈ 2.7 s, 201 ≈ 5.5 s). Device limits: NanoVNA‑H 101, NanoVNA‑H4 up to 401 (firmware dependent), NanoVNA V2 up to 1024; higher values are reduced automatically to the device maximum. |
| `--host ADDR` | `0.0.0.0` | Network address the web server listens on. `0.0.0.0` = reachable from other devices in the network; `127.0.0.1` = only from this computer. |
| `--http-port N` | `8000` | Port of the web server. Change it if 8000 is already in use (the app tells you when it is). |
| `--url URL` | detected | Address used for the phone link and QR code, e.g. `http://192.168.1.20:8000`. Only needed if the detected address is wrong (VPN, several network adapters). |
| `--tray` | off | Show a tray / menu-bar icon with **Open in browser** and **Quit**. Needs the extra packages: `uv sync --extra tray` (included in the standalone executables). |
| `--version` | | Print the version and exit. |

The app limits the sweep range to what the connected device supports: NanoVNA V2 / SAA‑2N 50 kHz – 3 GHz, NanoVNA‑H/H4 10 kHz – 1.5 GHz. A start/stop range outside this is rejected on the page, and the start-up range is adjusted automatically.

Tip: the step between points is (stop − start) / (points − 1). For 1–30 MHz with 101 points that is 290 kHz, which can miss a sharp resonance. Use **Zoom to min** or a band preset instead of raising the points.

## Calibration (NanoVNA V2 family only)

The page shows **Open / Short / Load** buttons when a V2-family device is connected:

1. Set the sweep range you want to use (e.g. 1–30 MHz).
2. Connect the **Open** standard where the antenna will be connected (end of the cable), tap **Open** and wait until the button turns green (one sweep).
3. Repeat with **Short** and **Load** (50 Ω).

The calibration is saved in `~/.nanovna-tuner/calibration.json` and reused after restarts; the page shows the calibrated range and date. Zooming or changing `--points` inside the calibrated range needs no recalibration; a range outside it, or a different cable/adapter, does. If you change the range in the middle of a calibration, the standards measured so far are discarded and the page tells you so. **Clear** deletes the calibration.

## Access and security

Other devices need an access token, which is embedded in the QR code and the printed phone link. The phone remembers it after the first visit. The token is stored in `~/.nanovna-tuner/token`; delete the file and restart to generate a new one (phones then need to scan the QR code again). The computer running the app can always use `http://localhost:8000` without a token.

Traffic is plain HTTP, so the app is meant for your home network, not the internet.

## Files

| Path | Content |
|---|---|
| `~/.nanovna-tuner/calibration.json` | Saved calibration (NanoVNA V2 family) |
| `~/.nanovna-tuner/token` | Access token for other devices |

## Development

```sh
uv sync                              # installs runtime + test dependencies
uv run python -m pytest              # runs the tests (no hardware needed)
uv run --extra tray --with pyinstaller pyinstaller --distpath build/dist --workpath build/work packaging/nanovna-tuner.spec
```

The last command builds a standalone executable for the current OS in `build/dist/`.

GitHub Actions runs the tests on macOS, Windows and Linux for every push. To publish a release, set the version in `nanovna_tuner/__init__.py`, commit, and push a matching tag (e.g. `git tag v0.2.0 && git push origin v0.2.0`); the executables for all three systems are then built and attached to a GitHub release automatically.

## License

Copyright © 2026 Andreas Karpf

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

In short: you may use, study, share and modify it freely. If you distribute it or a modified version, you must do so under the same license and make the source code available.
