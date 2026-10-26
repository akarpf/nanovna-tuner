import argparse
import logging
import socket
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .calibration import Calibration
from .nanovna import SimulatedNanoVNA, open_device
from .server import SweepWorker, create_app, load_token


def lan_ip() -> str:
    # UDP connect sends nothing; it only selects the outgoing interface
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def points(value: str) -> int:
    n = int(value)
    if not 11 <= n <= 1024:
        raise argparse.ArgumentTypeError("must be between 11 and 1024")
    return n


def bind(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # on Windows SO_REUSEADDR would allow stealing a port that is in use
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sys.exit(f"Port {port} is already in use - is nanovna-tuner already running? "
                 f"Stop it or choose another port with --http-port.")
    return sock


def main() -> None:
    p = argparse.ArgumentParser(description="Serve live NanoVNA SWR sweeps over HTTP")
    p.add_argument("--version", action="version", version=f"nanovna-tuner {__version__}")
    p.add_argument("--port", help="serial port (default: auto-detect)")
    p.add_argument("--simulate", action="store_true", help="use a simulated antenna instead of a NanoVNA")
    p.add_argument("--start", type=float, default=1.0, help="start frequency in MHz (default 1)")
    p.add_argument("--stop", type=float, default=30.0, help="stop frequency in MHz (default 30)")
    p.add_argument("--points", type=points, default=101, help="points per sweep, 11-1024 (default 101)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP bind address (default 0.0.0.0)")
    p.add_argument("--http-port", type=int, default=8000, help="HTTP port (default 8000)")
    p.add_argument("--url", help="address for the phone link/QR code, e.g. http://192.168.1.20:8000 "
                                 "(default: detected automatically)")
    p.add_argument("--tray", action="store_true", help="show a tray / menu-bar icon (needs: uv sync --extra tray)")
    args = p.parse_args()
    if args.stop <= args.start:
        p.error("--stop must be greater than --start")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.tray:
        try:
            from .tray import run_with_tray
        except ImportError:
            sys.exit("--tray needs extra packages: uv sync --extra tray")

    sock = bind(args.host, args.http_port)

    connect = SimulatedNanoVNA if args.simulate else (lambda: open_device(args.port))
    config_dir = Path.home() / ".nanovna-tuner"
    calibration = Calibration(config_dir / "calibration.json")
    token = load_token(config_dir / "token")
    worker = SweepWorker(connect, int(args.start * 1e6), int(args.stop * 1e6), args.points, calibration)
    worker.start()

    url = (args.url or f"http://{lan_ip()}:{args.http_port}").rstrip("/")
    local_url = f"http://localhost:{args.http_port}"
    print(f"\n  On this computer:   {local_url}  (shows a QR code for the phone)")
    print(f"  Open on your phone: {url}/?t={token}\n", flush=True)

    config = uvicorn.Config(create_app(worker, url, token), log_level="warning", timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    if args.tray:
        run_with_tray(server, [sock], local_url)
    else:
        server.run(sockets=[sock])


if __name__ == "__main__":
    main()
