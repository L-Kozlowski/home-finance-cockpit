"""Separate installed read-only resources from writable per-user application data."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = (
    Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PROJECT_ROOT
)


def data_directory():
    """Keep developer data in place; installed releases never write beside the EXE."""
    override = os.environ.get("HFC_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if not getattr(sys, "frozen", False):
        return PROJECT_ROOT / "data"
    if sys.platform == "win32":
        base = (
            Path(os.environ["LOCALAPPDATA"])
            if os.environ.get("LOCALAPPDATA")
            else Path.home() / "AppData" / "Local"
        )
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "HomeFinanceCockpit"


def reports_directory():
    return (
        data_directory() / "reports" if getattr(sys, "frozen", False) else PROJECT_ROOT / "reports"
    )


def ensure_data_directory():
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
