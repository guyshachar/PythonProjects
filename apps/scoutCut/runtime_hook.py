"""
PyInstaller runtime hook for scoutCut.

Runs before the application starts when launched from the frozen bundle.
Adds the bundled directory to PATH so the embedded ffmpeg/ffprobe are found,
and points Playwright at the system browser cache (browsers are not bundled).
"""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    bundle_dir = Path(sys._MEIPASS)

    # Make bundled ffmpeg/ffprobe visible to shutil.which()
    os.environ["PATH"] = str(bundle_dir) + os.pathsep + os.environ.get("PATH", "")

    # Playwright: use the system-installed browsers (not bundled — too large)
    for candidate in [
        Path.home() / "Library" / "Caches" / "ms-playwright",   # macOS
        Path.home() / ".cache" / "ms-playwright",                # Linux
    ]:
        if candidate.exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(candidate))
            break
