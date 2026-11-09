"""One version identity for staging, building, verifying and packaging releases."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from home_finance_cockpit.identity import APP_ARTIFACT_PREFIX, APP_VERSION

RELEASE = ROOT / f"version_{APP_VERSION}"
PREFIX = APP_ARTIFACT_PREFIX
