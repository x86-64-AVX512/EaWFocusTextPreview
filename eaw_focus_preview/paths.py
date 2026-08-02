from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Возвращает корень ресурсов и в исходниках, и в PyInstaller-сборке."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def fonts_directory() -> Path:
    return resource_root() / "assets" / "fonts"
