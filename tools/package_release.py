"""Package the tested snapshot, standalone app and corresponding dependency sources."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from release_paths import PREFIX, RELEASE


def archive_tree(source, destination, prefix=""):
    count = 0
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(source.rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in (".pyc", ".pyo")
                or any(part.endswith(".egg-info") for part in path.parts)
            ):
                continue
            archive.write(path, str(Path(prefix) / path.relative_to(source)))
            count += 1
    return count


def package():
    artifacts = RELEASE / "artifacts"
    artifacts.mkdir(exist_ok=True)
    for name in ("frozen-check.json", "msi-check.json", "msi-payload-check.json"):
        outcome = json.loads((RELEASE / "verification" / name).read_text(encoding="utf-8"))
        assert outcome["passed"], f"Cannot package failed verification: {name}"
    files = json.loads((RELEASE / "source-manifest.json").read_text(encoding="utf-8"))
    for filename, expected in files.items():
        actual = hashlib.sha256((RELEASE / "source" / filename).read_bytes()).hexdigest()
        assert actual == expected, f"Staged source changed after manifest: {filename}"
    archive_tree(RELEASE / "source", artifacts / f"{PREFIX}-source.zip", "source")
    archive_tree(
        RELEASE / "build/application",
        artifacts / f"{PREFIX}-portable-windows-x64.zip",
        "HomeFinanceCockpit",
    )
    archive_tree(RELEASE / "third_party_sources", artifacts / f"{PREFIX}-third-party-sources.zip")
    archive_tree(RELEASE / "source/example", artifacts / f"{PREFIX}-examples.zip", "example")
    for name in ("LICENSE", "COPYRIGHT.md", "SOURCE_CODE.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(RELEASE / "source" / name, artifacts / name)
    shutil.copy2(RELEASE / "source/docs/BETA_TESTING.md", artifacts / "BETA_TESTING.md")
    shutil.copy2(RELEASE / "source-manifest.json", artifacts / "source-manifest.json")
    for name in ("frozen-check.json", "msi-check.json", "msi-payload-check.json"):
        shutil.copy2(RELEASE / "verification" / name, artifacts / name)
    shutil.copy2(RELEASE / "DISTRIBUTION_README.md", artifacts / "README.md")
    hashes = []
    for path in sorted(artifacts.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            with path.open("rb") as stream:
                hashes.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}")
    (artifacts / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    # MSI and source archives are already compressed. Store the outer transport
    # ZIP without recompression and keep it outside artifacts to avoid recursion.
    bundle = RELEASE / f"{PREFIX}-distribution.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(artifacts.iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    with bundle.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    (RELEASE / "DISTRIBUTION_SHA256.txt").write_text(
        f"{checksum}  {bundle.name}\n", encoding="utf-8"
    )
    print(f"Packaged {len(hashes)} distribution files in {artifacts}")


if __name__ == "__main__":
    package()
