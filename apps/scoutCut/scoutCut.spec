# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for scoutCut.

Bundles:
  - scoutCut.py (main script)
  - pixellot_scraper.py + veo_scraper.py (platform scrapers)
  - All Python dependencies (yt-dlp, Pillow, playwright, google-api-*)
  - ffmpeg + ffprobe binaries (from Homebrew)

NOT bundled (must be pre-installed on target machine):
  - Playwright Chromium browser  →  run: playwright install chromium
  - veo_profile/ session dir     →  run veo_scraper.py once to log in

Build:
    python3.11 -m PyInstaller scoutCut.spec
Output:
    dist/scoutCut   (one-dir bundle)
"""

import shutil
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# ── Collect Python packages ────────────────────────────────────────────────
yt_datas,   yt_bins,   yt_hidden   = collect_all("yt_dlp")
pw_datas,   pw_bins,   pw_hidden   = collect_all("playwright")
pil_datas,  pil_bins,  pil_hidden  = collect_all("PIL")
ga_datas,   ga_bins,   ga_hidden   = collect_all("google")
gac_datas,  gac_bins,  gac_hidden  = collect_all("googleapiclient")
req_datas,  req_bins,  req_hidden  = collect_all("requests")

# ── Bundle ffmpeg + ffprobe ────────────────────────────────────────────────
extra_bins = []
for tool in ("ffmpeg", "ffprobe"):
    path = shutil.which(tool)
    if path:
        extra_bins.append((path, "."))

# ── Analysis ──────────────────────────────────────────────────────────────
a = Analysis(
    ["scoutCut.py"],
    pathex=["."],
    binaries=extra_bins + yt_bins + pw_bins + pil_bins + ga_bins + gac_bins + req_bins,
    datas=yt_datas + pw_datas + pil_datas + ga_datas + gac_datas + req_datas,
    hiddenimports=(
        ["pixellot_scraper", "veo_scraper"]
        + yt_hidden + pw_hidden + pil_hidden + ga_hidden + gac_hidden + req_hidden
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook.py"],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="scoutCut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="scoutCut",
)
