"""Offline checks before building; this does not certify a completed installer."""

import importlib.metadata as metadata
import json
import platform
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from home_finance_cockpit.identity import APP_ARTIFACT_PREFIX, APP_RELEASE, APP_VERSION


def check():
    errors = []
    pins = {}
    for line in (ROOT / "requirements-runtime-lock.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            pins[canonicalize_name(name)] = version
    for filename in (
        "requirements.txt",
        "requirements-build.txt",
        "requirements-dev.txt",
        "requirements-runtime-lock.txt",
    ):
        for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            requirement = Requirement(line)
            try:
                version = metadata.version(requirement.name)
                if not requirement.specifier.contains(version):
                    errors.append(f"{filename}: installed version does not match {line}")
            except metadata.PackageNotFoundError:
                errors.append(f"Missing installed package: {requirement.name}")
    for name in pins:
        for text in metadata.requires(name) or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            if canonicalize_name(requirement.name) not in pins:
                errors.append(f"Unpinned runtime dependency: {name} -> {requirement.name}")
    if (
        platform.system() != "Windows"
        or struct.calcsize("P") != 8
        or sys.version_info[:3] != (3, 12, 10)
    ):
        errors.append("The release build targets Windows x64 with Python 3.12.10")
    if not re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION):
        errors.append("MSI requires a three-part numeric version")
    inventory = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8"))
    recorded = {canonicalize_name(item["name"]) for item in inventory["packages"]}
    if set(pins) - recorded:
        errors.append("Runtime inventory is incomplete")
    for item in inventory["packages"]:
        if item["version"] != metadata.version(item["name"]):
            errors.append(f"Stale dependency inventory: {item['name']}")
        if not item["notices"] or any(not (ROOT / path).is_file() for path in item["notices"]):
            errors.append(f"Missing license notices: {item['name']}")
    for relative in (
        "LICENSE",
        "COPYRIGHT.md",
        "SOURCE_CODE.md",
        "THIRD_PARTY_NOTICES.md",
        "licenses/PYTHON.txt",
        "licenses/SQLCIPHER.txt",
        "licenses/OPENSSL.txt",
        "licenses/MSVC-REDIST.txt",
        "licenses/installer-license.rtf",
        "home_finance_cockpit/ui/assets/branding/app-icon.ico",
        "home_finance_cockpit/ui/assets/branding/reports/wordmark.png",
        "home_finance_cockpit/locales/en.json",
    ):
        if not (ROOT / relative).is_file():
            errors.append(f"Missing build resource: {relative}")
    for filename in ("SOURCE_CODE.md", "THIRD_PARTY_NOTICES.md", "licenses/installer-license.rtf"):
        if APP_RELEASE not in (ROOT / filename).read_text(encoding="utf-8"):
            errors.append(f"Stale release in legal document: {filename}")
    return dict(
        release=APP_RELEASE,
        artifact_prefix=APP_ARTIFACT_PREFIX,
        passed=not errors,
        errors=errors,
        remaining=[
            "Download and verify exact corresponding dependency sources before distribution.",
            "Build and verify the frozen executable and MSI payload.",
            "Test install, upgrade and uninstall on a clean Windows account/machine.",
            "Complete the distribution README after building, as requested.",
            "Confirm rights to supplied branding assets before public distribution.",
        ],
    )


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
