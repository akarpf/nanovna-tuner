import argparse
import logging
import socket
from pathlib import Path

import uvicorn

from .calibration import Calibration
from .nanovna import SimulatedNanoVNA, open_device
from .server import SweepWorker, create_app


def lan_ip() -> str:
    # UDP connect sends nothing; it only selects the outgoing interface
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> None:
    p = argparse.ArgumentParser(description="Serve live NanoVNA SWR sweeps over HTTP")
    p.add_argument("--port", help="serial port (default: auto-detect)")
    p.add_argument("--simulate", action="store_true", help="use a simulated antenna instead of a NanoVNA")
    p.add_argument("--start", type=float, default=1.0, help="start frequency in MHz (default 1)")
    p.add_argument("--stop", type=float, default=30.0, help="stop frequency in MHz (default 30)")
    p.add_argument("--points", type=int, default=101, help="points per sweep (default 101)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP bind address (default 0.0.0.0)")
    p.add_argument("--http-port", type=int, default=8000, help="HTTP port (default 8000)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    connect = SimulatedNanoVNA if args.simulate else (lambda: open_device(args.port))
    calibration = Calibration(Path.home() / ".nanovna-tuner" / "calibration.json")
    worker = SweepWorker(connect, int(args.start * 1e6), int(args.stop * 1e6), args.points, calibration)
    worker.start()

    url = f"http://{lan_ip()}:{args.http_port}"
    print(f"\n  Open on your phone:  {url}\n")
    uvicorn.run(create_app(worker, url), host=args.host, port=args.http_port, log_level="warning")


if __name__ == "__main__":
    main()
