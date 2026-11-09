"""Application identity, independent of the desktop and report implementations."""

from pathlib import Path

APP_NAME = "Home Finance Cockpit"
APP_VERSION = "1.0.0"
APP_BETA = None
APP_RELEASE = f"{APP_VERSION} Beta {APP_BETA}" if APP_BETA is not None else APP_VERSION
APP_ARTIFACT_PREFIX = f"HomeFinanceCockpit-{APP_VERSION}" + (
    f"-Beta{APP_BETA}" if APP_BETA is not None else ""
)
APP_AUTHOR = "Łukasz Kozłowski"
APP_COPYRIGHT = f"Copyright © 2026 {APP_AUTHOR}"
APP_LICENSE = "GPL-3.0-only"
WINDOWS_APP_ID = "HomeFinanceCockpit.Desktop"
BRAND_ASSETS = Path(__file__).resolve().parent / "ui" / "assets" / "branding"
