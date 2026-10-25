# nanovna-tuner

Live NanoVNA antenna measurements (SWR, return loss, impedance, Smith chart) served over the local Wi‑Fi to any browser/phone.

## Usage

Requires [uv](https://docs.astral.sh/uv/). Plug in the NanoVNA (NanoVNA / -H / -H4 text-shell firmware), then:

```sh
uv run python -m nanovna_tuner                 # auto-detects the NanoVNA
uv run python -m nanovna_tuner --simulate      # no hardware, simulated 20 m antenna
uv run python -m nanovna_tuner --port /dev/cu.usbmodem401 --start 13.5 --stop 14.8
```

The NanoVNA can be plugged in (or re-plugged) at any time; the app retries every 2 s and reconnects automatically.

Supported: NanoVNA / -H / -H4 (uses the device's own calibration) and NanoVNA V2 / V2 Plus4 / LiteVNA. The V2 family sends uncalibrated data over USB, so the page shows **Open / Short / Load** buttons: set the sweep range, connect each standard where the antenna will be connected and tap its button. The calibration is saved in `~/.nanovna-tuner/calibration.json`; zooming inside the calibrated range needs no recalibration.

Open the printed `http://<ip>:8000` on a phone in the same Wi‑Fi, or open it on the Mac and scan the QR code in the lower right corner. It shows the frequency of minimum SWR, the SWR value, the SWR < 2 bandwidth and the SWR curve. Use the band selector or **Zoom to min** to narrow the sweep around the resonance.

The server has no authentication; only run it on a trusted network.
