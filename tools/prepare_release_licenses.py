"""Preserve upstream native-library notices and create the installer license view."""

import shutil
import tarfile

from collect_release_sources import TARGET, fetch
from stage_release import RELEASE, ROOT

from home_finance_cockpit.identity import APP_RELEASE


def prepare():
    from freeze_core import winmsvcr_repack

    directory = ROOT / "licenses"
    directory.mkdir(exist_ok=True)
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    rtf = text.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
    (directory / "installer-license.rtf").write_text(
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Segoe UI;}}\f0\fs16 "
        + f"Home Finance Cockpit {APP_RELEASE} - GPLv3\\par "
        + r"Copyright 2026 \u321?ukasz Koz\u322?owski\par\par "
        + rtf.replace("\n", "\\par\n")
        + "}",
        encoding="utf-8",
    )

    # Freeze-core downloads the official redistributable, extracts DLLs and its EULA.
    # Keep the build cache inside the release rather than the developer's profile.
    winmsvcr_repack.VC_REDIST_CACHE = RELEASE / "build/tool-cache/vc_redist"
    files = list(winmsvcr_repack.get_msvcr_files(17, "win-amd64"))
    for path in files:
        if path.name == "LICENSE.txt":
            (directory / "MSVC-REDIST.txt").write_text(
                path.read_text(encoding="cp1252"), encoding="utf-8"
            )
        elif path.name == "LICENSE.RTF":
            shutil.copy2(path, directory / "MSVC-REDIST.rtf")

    # The sqlcipher3 source includes its adapter and amalgamation, but OpenSSL is
    # obtained separately by its wheel build. Preserve exact native build versions.
    with tarfile.open(TARGET / "sqlcipher3-0.6.4.tar.gz") as archive:
        conan = archive.extractfile("sqlcipher3-0.6.4/conanfile.py").read().decode()
        (TARGET / "sqlcipher3-native-build.py").write_text(conan, encoding="utf-8")
        print(conan, flush=True)
    for name, url in (
        (
            "SQLCIPHER.txt",
            "https://raw.githubusercontent.com/sqlcipher/sqlcipher/v4.19.0/LICENSE.md",
        ),
        (
            "OPENSSL.txt",
            "https://raw.githubusercontent.com/openssl/openssl/openssl-3.6.0/LICENSE.txt",
        ),
    ):
        with fetch(url) as response:
            (directory / name).write_bytes(response.read())
    print("Prepared installer and native dependency licenses", flush=True)


if __name__ == "__main__":
    prepare()
