# Copyright (C) 2026 Andreas Karpf
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import threading
import webbrowser

import uvicorn


def _icon_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(0, 87, 217, 255))
    # stylised SWR dip
    d.line([(10, 20), (24, 22), (32, 48), (40, 22), (54, 20)], fill=(255, 255, 255, 255), width=5)
    return img


def _use_system_symbol(icon) -> None:
    """Replaces pystray's PNG->NSImage conversion, which crashes with PyObjC 12 on macOS 26, by an SF Symbol."""
    import AppKit

    def assert_image():
        if icon._icon_image is None:
            img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "antenna.radiowaves.left.and.right", "NanoVNA Tuner"
            )
            img.setTemplate_(True)
            icon._icon_image = img
            icon._status_item.button().setImage_(img)

    icon._assert_image = assert_image

def run_with_tray(server: uvicorn.Server, sockets: list, local_url: str) -> None:
    """Runs the web server in a thread and a tray/menu-bar icon on the main thread (required on macOS)."""
    import pystray

    def quit_app(icon, _item):
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "nanovna-tuner",
        _icon_image(),
        "NanoVNA Tuner",
        menu=pystray.Menu(
            pystray.MenuItem("Open in browser", lambda: webbrowser.open(local_url), default=True),
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    if sys.platform == "darwin":
        _use_system_symbol(icon)

    def show(icon):
        # pystray calls this from a worker thread; AppKit must only be touched on the main thread
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(setattr, icon, "visible", True)
        else:
            icon.visible = True

    threading.Thread(target=server.run, kwargs={"sockets": sockets}, daemon=True).start()
    icon.run(setup=show)
