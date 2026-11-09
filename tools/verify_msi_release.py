"""Inspect and administratively extract the MSI without installing it on the developer PC."""

import json
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from release_paths import PREFIX, RELEASE
from verify_frozen_release import verify

from home_finance_cockpit.identity import APP_AUTHOR, APP_VERSION


def rows(database, table, fields):
    view = database.OpenView(f"SELECT {', '.join(fields)} FROM {table}")
    view.Execute(None)
    result = []
    while record := view.Fetch():
        result.append([record.GetString(index + 1) for index in range(len(fields))])
    view.Close()
    return result


def main():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="'msilib' is deprecated", category=DeprecationWarning
        )
        import msilib

    release = RELEASE
    installer = release / "artifacts" / f"{PREFIX}-windows-x64.msi"
    verification = release / "verification"
    verification.mkdir(exist_ok=True)
    database = msilib.OpenDatabase(str(installer), msilib.MSIDBOPEN_READONLY)
    properties = dict(rows(database, "Property", ["Property", "Value"]))
    assert properties["Manufacturer"] == APP_AUTHOR
    assert properties["ProductVersion"] == APP_VERSION
    assert not properties.get("ALLUSERS")
    assert not properties.get("MSIINSTALLPERUSER")
    assert properties["UpgradeCode"] == "{A758DB3E-7C0E-45E0-BFE9-720AB0563DD9}"
    summary = database.GetSummaryInformation(0)
    assert summary.GetProperty(15) & 8, "Installer is not marked limited-user compatible"
    assert "x64" in str(summary.GetProperty(7))
    files = rows(database, "File", ["FileName"])
    names = [name[0].split("|")[-1] for name in files]
    for name in (
        "HomeFinanceCockpit.exe",
        "python312.dll",
        "LICENSE",
        "SOURCE_CODE.md",
        "THIRD_PARTY_NOTICES.md",
        "dependencies.json",
    ):
        assert name in names, f"Missing installer payload: {name}"
    assert not any(name.endswith((".db", ".sqlite", ".ini")) for name in names)
    assert "Qt6Pdf.dll" not in names and "qpdf.dll" not in names
    shortcuts = rows(database, "Shortcut", ["Name", "Directory_"])
    assert any(directory == "HFCProgramMenu" for _, directory in shortcuts)
    conditions = rows(database, "LaunchCondition", ["Condition", "Description"])
    assert any("REMOVENEWVERSION" in condition for condition, _ in conditions)
    database.Close()

    # Administrative extraction reads the package into our workspace. It does not
    # register an installation, create user shortcuts or change system settings.
    extracted = verification / "msi-extracted"
    process = subprocess.run(
        [
            "msiexec.exe",
            "/a",
            str(installer),
            "/qn",
            f"TARGETDIR={extracted}",
            "/L*v",
            str(verification / "msi-extraction.log"),
        ],
        timeout=180,
        capture_output=True,
    )
    assert process.returncode == 0, f"MSI extraction failed: {process.returncode}"
    executables = list(extracted.rglob("HomeFinanceCockpit.exe"))
    assert len(executables) == 1
    verify(executables[0], verification / "msi-payload-check.json")
    outcome = {
        "passed": True,
        "manufacturer": APP_AUTHOR,
        "version": APP_VERSION,
        "payload_files": len(names),
        "per_user_package": True,
        "sources_and_licenses_notices_present": True,
        "no_database_or_private_settings_in_installer": True,
        "administrative_extraction_and_payload_self_test": True,
        "clean_windows_vm_tested": False,
        "interactive_install_upgrade_uninstall_tested": False,
    }
    (verification / "msi-check.json").write_text(
        json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("MSI metadata, extraction and payload checks passed")


if __name__ == "__main__":
    main()
