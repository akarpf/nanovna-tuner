# Copyright (C) 2026 Andreas Karpf
# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller recipe for a single-file executable: uv run --with pyinstaller pyinstaller packaging/nanovna-tuner.spec
import os

from PyInstaller.utils.hooks import collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(root, "packaging", "entry.py")],
    pathex=[root],
    datas=[(os.path.join(root, "nanovna_tuner", "static"), "nanovna_tuner/static")],
    # pystray picks its platform backend at runtime
    hiddenimports=collect_submodules("pystray"),
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="nanovna-tuner", console=True, upx=False)
