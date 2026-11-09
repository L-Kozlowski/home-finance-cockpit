"""Create a clean release snapshot from an explicit allowlist, never from user data."""

import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from release_paths import RELEASE, ROOT

SOURCE = RELEASE / "source"
RUNTIME = (
    "PyQt6",
    "PyQt6-Qt6",
    "PyQt6-sip",
    "matplotlib",
    "numpy",
    "openpyxl",
    "et_xmlfile",
    "sqlcipher3",
    "reportlab",
    "pillow",
    "charset-normalizer",
    "contourpy",
    "cycler",
    "fonttools",
    "kiwisolver",
    "packaging",
    "pyparsing",
    "python-dateutil",
    "six",
)
SUPPORT = ("cx-Freeze", "freeze-core", "lief", "cabarchive", "filelock", "striprtf", "setuptools")
SOURCE_DIRECTORIES = ("home_finance_cockpit", "tests", "tools", "example", "demo-img")


def archive_unlisted_packages():
    """Do not carry an obsolete application package into a rebuilt source release."""
    archived = []
    for package in SOURCE.iterdir():
        if package.name in SOURCE_DIRECTORIES or not (package / "__init__.py").is_file():
            continue
        target = RELEASE / "build/previous-source-packages" / uuid4().hex / package.name
        if not package.resolve().is_relative_to(
            SOURCE.resolve()
        ) or not target.resolve().is_relative_to(RELEASE.resolve()):
            raise ValueError("Source package archive must stay within the release directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        package.replace(target)
        archived.append(target)
    return archived


def ignored(directory, names):
    example = Path(directory).resolve().is_relative_to((ROOT / "example").resolve())
    return {
        name
        for name in names
        if name in ("__pycache__", ".ruff_cache", "ui-concepts", "ui-conepts", ".pytest_cache")
        or name.endswith((".pyc", ".pyo"))
        or name == "settings.ini"
        or (example and name in ("backups", "logs", "source"))
        or (
            example
            and name.lower().endswith(
                (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal")
            )
            and (Path(directory) / name).resolve()
            != (ROOT / "example/database/home_finance_demo.db").resolve()
        )
    }


def stage():
    RELEASE.mkdir(exist_ok=True)
    SOURCE.mkdir(exist_ok=True)
    archive_unlisted_packages()
    for directory in SOURCE_DIRECTORIES:
        shutil.copytree(ROOT / directory, SOURCE / directory, dirs_exist_ok=True, ignore=ignored)
    (SOURCE / "docs").mkdir(exist_ok=True)
    for filename in ("DEVELOPMENT.md", "BETA_TESTING.md", "BUILD_WINDOWS.md"):
        path = ROOT / "docs" / filename
        if path.is_file():
            shutil.copy2(path, SOURCE / "docs" / filename)
    for filename in (
        "main.py",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        "requirements-runtime-lock.txt",
        "requirements-dev.txt",
        "requirements-build.txt",
        "LICENSE",
        "COPYRIGHT.md",
        "THIRD_PARTY_NOTICES.md",
        "SOURCE_CODE.md",
        ".gitignore",
    ):
        shutil.copy2(ROOT / filename, SOURCE / filename)
    shutil.copytree(ROOT / "licenses", SOURCE / "licenses", dirs_exist_ok=True)
    inventory = []
    license_root = SOURCE / "licenses/third-party"
    for name in (*RUNTIME, *SUPPORT):
        distribution = metadata.distribution(name)
        target = license_root / re.sub(r"[^a-z0-9-]", "-", name.lower())
        target.mkdir(parents=True, exist_ok=True)
        notices = []
        for item in distribution.files or []:
            path = Path(str(item))
            if any(
                word in path.name.lower() for word in ("license", "licence", "copying", "notice")
            ):
                source = distribution.locate_file(item)
                if source.is_file():
                    # Preserve the full original path to avoid duplicate license basenames.
                    destination = target / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    notices.append(str(destination.relative_to(SOURCE)).replace("\\", "/"))
        if not notices:
            notices = [
                path.relative_to(SOURCE).as_posix() for path in target.rglob("*") if path.is_file()
            ]
        if not notices:
            raise ValueError(f"Missing upstream license notices: {name}")
        inventory.append(
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
                "license": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or "See bundled notices",
                "purpose": "runtime" if name in RUNTIME else "build tooling",
                "notices": notices,
            }
        )
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    shutil.copy2(python_license, SOURCE / "licenses/PYTHON.txt")
    (SOURCE / "dependencies.json").write_text(
        json.dumps(
            {"python": sys.version.split()[0], "packages": inventory}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    (SOURCE / "requirements-runtime-lock.txt").write_text(
        "# Exact runtime resolved for Windows x64 / Python 3.12.10.\n"
        + "".join(
            f"{metadata.distribution(name).metadata['Name']}=={metadata.version(name)}\n"
            for name in RUNTIME
        ),
        encoding="utf-8",
    )
    files = {
        str(path.relative_to(SOURCE)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(SOURCE.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in (".pyc", ".pyo")
        and not any(part.endswith(".egg-info") for part in path.parts)
    }
    (RELEASE / "source-manifest.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    print(f"Staged {len(files)} files in {SOURCE}")


if __name__ == "__main__":
    stage()
