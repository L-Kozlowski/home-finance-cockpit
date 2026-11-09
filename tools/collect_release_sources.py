"""Download exact upstream source archives and preserve their verified provenance."""

import hashlib
import importlib.metadata as metadata
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

from stage_release import RELEASE, ROOT, RUNTIME, SUPPORT

from home_finance_cockpit.identity import APP_VERSION

TARGET = RELEASE / "third_party_sources"


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": f"HomeFinanceCockpit-release/{APP_VERSION}"}
    )
    return urllib.request.urlopen(request, timeout=60)


def download(url, filename, expected=None):
    path = TARGET / filename
    if path.is_file() and (expected is None or digest(path) == expected):
        return path
    temporary = path.with_name(path.name + ".partial")
    print(f"Downloading {filename}", flush=True)
    with fetch(url) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = digest(temporary)
    if expected is not None and actual != expected:
        raise ValueError(f"SHA-256 mismatch: {filename}")
    temporary.replace(path)
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect():
    TARGET.mkdir(parents=True, exist_ok=True)
    inventory = []

    def record(name, version, path, url, verification):
        inventory.append(
            dict(
                name=name,
                version=version,
                filename=path.name,
                url=url,
                sha256=digest(path),
                verification=verification,
            )
        )
        (TARGET / "manifest.json").write_text(
            json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    for name in (*RUNTIME, *SUPPORT):
        if name == "PyQt6-Qt6":
            continue
        version = metadata.version(name)
        with fetch(f"https://pypi.org/pypi/{name}/{version}/json") as response:
            data = json.load(response)
        source = next(item for item in data["urls"] if item["packagetype"] == "sdist")
        archive = download(source["url"], source["filename"], source["digests"]["sha256"])
        record(name, version, archive, source["url"], "PyPI SHA-256")

    qt_version = metadata.version("PyQt6-Qt6")
    qt_series = ".".join(qt_version.split(".")[:2])
    for module in ("qtbase", "qtsvg", "qtimageformats", "qttranslations"):
        filename = f"{module}-everywhere-src-{qt_version}.tar.xz"
        url = f"https://download.qt.io/archive/qt/{qt_series}/{qt_version}/submodules/{filename}"
        with fetch(url + ".sha256") as response:
            expected = response.read().decode("ascii").split()[0]
        archive = download(url, filename, expected)
        record(module, qt_version, archive, url, "Qt published SHA-256")
        if module == "qtbase":
            with tarfile.open(archive) as source:
                for member in source.getmembers():
                    if "/LICENSES/" in member.name and member.isfile():
                        destination = ROOT / "licenses/qt" / Path(member.name).name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with source.extractfile(member) as stream:
                            destination.write_bytes(stream.read())

    filename = "Python-3.12.10.tar.xz"
    url = f"https://www.python.org/ftp/python/3.12.10/{filename}"
    archive = download(url, filename)
    record("Python", "3.12.10", archive, url, "HTTPS upstream; local SHA-256 recorded")
    filename = "openssl-3.6.0.tar.gz"
    url = "https://github.com/openssl/openssl/releases/download/openssl-3.6.0/" + filename
    with fetch(url + ".sha256") as response:
        expected = response.read().decode("ascii").split()[0]
    archive = download(url, filename, expected)
    record("OpenSSL (SQLCipher)", "3.6.0", archive, url, "OpenSSL published SHA-256")
    print(f"Collected {len(inventory)} source archives", flush=True)


if __name__ == "__main__":
    collect()
