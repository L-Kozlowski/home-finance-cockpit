"""Verify companion sources and transport archives against their manifests."""

import hashlib
import json
import zipfile
from pathlib import Path

from release_paths import PREFIX, RELEASE

ARTIFACTS = RELEASE / "artifacts"


def main():
    with zipfile.ZipFile(ARTIFACTS / f"{PREFIX}-source.zip") as archive:
        names = archive.namelist()
        manifest = json.loads((ARTIFACTS / "source-manifest.json").read_text(encoding="utf-8"))
        assert set(names) == {"source/" + name for name in manifest}
        for filename, expected in manifest.items():
            assert hashlib.sha256(archive.read("source/" + filename)).hexdigest() == expected
        for name in names:
            parts = Path(name).parts
            assert not set(parts) & {".git", ".venv", ".local", "other", "__pycache__"}
            assert not any(part.endswith(".egg-info") for part in parts)
            assert "settings.ini" not in parts
            if name.endswith((".db", ".sqlite", ".sqlite3")):
                assert name == "source/example/database/home_finance_demo.db"

    with zipfile.ZipFile(ARTIFACTS / f"{PREFIX}-third-party-sources.zip") as archive:
        inventory = json.loads(archive.read("manifest.json"))
        for item in inventory:
            assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
    for line in (ARTIFACTS / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        with (ARTIFACTS / name).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
    bundle = RELEASE / f"{PREFIX}-distribution.zip"
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            path.name for path in ARTIFACTS.iterdir() if path.is_file()
        }
    expected, name = (RELEASE / "DISTRIBUTION_SHA256.txt").read_text().strip().split("  ", 1)
    with (RELEASE / name).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
    print("Source contents, privacy allowlist, upstream sources and distribution hashes verified")


if __name__ == "__main__":
    main()
