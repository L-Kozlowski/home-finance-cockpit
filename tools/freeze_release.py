"""Build the staged GPL release as an offline, per-user Windows MSI."""

import os
import sys
from pathlib import Path
from time import time_ns

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_msi import bdist_msi
from cx_Freeze.command.build_exe import build_exe
from freeze_core import winmsvcr_repack

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)

from home_finance_cockpit.identity import (
    APP_ARTIFACT_PREFIX,
    APP_AUTHOR,
    APP_COPYRIGHT,
    APP_NAME,
    APP_RELEASE,
    APP_VERSION,
)

RELEASE = SOURCE.parent if SOURCE.name == "source" else SOURCE / f"version_{APP_VERSION}"

ICON = SOURCE / "home_finance_cockpit/ui/assets/branding/app-icon.ico"
EXE = RELEASE / "build/application"
winmsvcr_repack.VC_REDIST_CACHE = RELEASE / "build/tool-cache/vc_redist"


class ReleaseBuild(build_exe):
    def run(self):
        super().run()
        import lief

        # The generic Qt hook collects every DLL/plugin from the Qt wheel,
        # including multimedia, QML and QtPDF. Archive unrelated modules instead
        # of distributing unused code and its unrelated licensing surface.
        qt = EXE / "lib/PyQt6/Qt6"
        excluded = RELEASE / "build/excluded-qt" / str(time_ns())

        def archive(path):
            if not path.resolve().is_relative_to(EXE.resolve()):
                raise ValueError("Unexpected path outside the frozen build")
            target = excluded / path.relative_to(EXE)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)

        allowed_plugins = {
            "generic",
            "iconengines",
            "imageformats",
            "networkinformation",
            "platforms",
            "styles",
            "tls",
        }
        for path in (qt / "plugins").iterdir():
            if path.name not in allowed_plugins:
                archive(path)
        if (qt / "qml").exists():
            archive(qt / "qml")
        for path in (qt / "plugins").rglob("qpdf.dll"):
            archive(path)
        for path in (qt / "translations").iterdir():
            if path.name not in ("qtbase_pl.qm", "qtbase_en.qm"):
                archive(path)

        binaries = {path.name.lower(): path for path in (qt / "bin").glob("*.dll")}
        queue = list((EXE / "lib/PyQt6").glob("*.pyd"))
        queue.extend((qt / "plugins").rglob("*.dll"))
        required = set()
        while queue:
            binary = lief.PE.parse(str(queue.pop()))
            if binary is None:
                raise ValueError("Cannot inspect Qt binary dependencies")
            names = list(binary.libraries) + [item.name for item in binary.delay_imports]
            for name in names:
                key = name.lower()
                if key in binaries and key not in required:
                    required.add(key)
                    queue.append(binaries[key])
        for name, path in binaries.items():
            if name not in required:
                archive(path)


class ReleaseMSI(bdist_msi):
    def run(self):
        super().run()
        import msilib

        installer = Path(self.dist_dir) / self.output_name
        database = msilib.OpenDatabase(str(installer), msilib.MSIDBOPEN_TRANSACT)
        # This is a fixed per-user package, not an MSI dual-context package.
        # MSIINSTALLPERUSER is ignored for limited-user-compatible packages;
        # leaving ALLUSERS=2 could otherwise select the machine context.
        for property_name in ("ALLUSERS", "MSIINSTALLPERUSER"):
            view = database.OpenView(f"DELETE FROM Property WHERE Property = '{property_name}'")
            view.Execute(None)
            view.Close()
        summary = database.GetSummaryInformation(2)
        # Mark the package as limited-user compatible, rather than merely setting
        # per-user properties while retaining a privileged-package summary flag.
        summary.SetProperty(15, int(summary.GetProperty(15) or 0) | 8)
        summary.SetProperty(14, 500)
        summary.Persist()
        database.Commit()
        database.Close()


INCLUDE = [
    (str(SOURCE / name), name)
    for name in (
        "LICENSE",
        "COPYRIGHT.md",
        "THIRD_PARTY_NOTICES.md",
        "SOURCE_CODE.md",
        "licenses",
        "dependencies.json",
    )
]
INCLUDE += [
    (str(SOURCE / "home_finance_cockpit/locales"), "lib/home_finance_cockpit/locales"),
    (str(SOURCE / "home_finance_cockpit/ui/assets"), "lib/home_finance_cockpit/ui/assets"),
]

setup(
    name="HomeFinanceCockpit",
    version=APP_VERSION,
    description=f"{APP_NAME} {APP_RELEASE}",
    author=APP_AUTHOR,
    license="GPL-3.0-only",
    cmdclass={"build_exe": ReleaseBuild, "bdist_msi": ReleaseMSI},
    options={
        "build": {"build_base": str(RELEASE / "build")},
        "build_exe": {
            "build_exe": str(EXE),
            "packages": ["home_finance_cockpit", "matplotlib", "openpyxl", "sqlcipher3"],
            "excludes": [
                "tkinter",
                "unittest",
                "pypdf",
                "ruff",
                "vulture",
                "pip",
                "setuptools",
                "test",
                "tests",
                "PyQt6.QtQml",
                "PyQt6.QtQuick",
                "PyQt6.QtWebEngineCore",
                "PyQt6.QtWebEngineWidgets",
            ],
            "include_files": INCLUDE,
            "include_msvcr": True,
            "silent_level": 1,
        },
        "bdist_msi": {
            "dist_dir": str(RELEASE / "artifacts"),
            "bdist_dir": str(RELEASE / "build/msi"),
            "output_name": f"{APP_ARTIFACT_PREFIX}-windows-x64.msi",
            "product_name": f"{APP_NAME} {APP_RELEASE}",
            "product_version": APP_VERSION,
            "upgrade_code": "{A758DB3E-7C0E-45E0-BFE9-720AB0563DD9}",
            "initial_target_dir": r"[LocalAppDataFolder]Programs\HomeFinanceCockpit",
            "all_users": False,
            "add_to_path": False,
            "install_icon": str(ICON),
            "license_file": str(SOURCE / "licenses/installer-license.rtf"),
            "launch_on_finish": False,
            "summary_data": {
                "author": APP_AUTHOR,
                "comments": "GPLv3 release; source code accompanies this installer.",
            },
            "data": {
                "Directory": [
                    ("ProgramMenuFolder", "TARGETDIR", "."),
                    ("HFCProgramMenu", "ProgramMenuFolder", "HFC|Home Finance Cockpit"),
                ],
                "LaunchCondition": [
                    ("VersionNT64", "64-bit Windows is required."),
                    ("Installed OR NOT REMOVENEWVERSION", "A newer version is already installed."),
                ],
            },
        },
    },
    executables=[
        Executable(
            str(SOURCE / "main.py"),
            base="gui",
            target_name="HomeFinanceCockpit.exe",
            icon=str(ICON),
            copyright=APP_COPYRIGHT,
            shortcut_name=APP_NAME,
            shortcut_dir="HFCProgramMenu",
        )
    ],
)
