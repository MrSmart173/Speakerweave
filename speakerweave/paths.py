"""Where the app's own files are, both when run from source and as a built .exe."""
from __future__ import annotations

import os
import sys


def is_built() -> bool:
    """True when running as the packaged SpeakerWeave.exe."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    if is_built():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource(name: str) -> str:
    return os.path.join(resource_dir(), name)
