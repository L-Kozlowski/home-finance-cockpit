"""Exercise a frozen EXE from a foreign working directory without developer paths."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def verify(executable, result):
    executable, result = executable.resolve(), result.resolve()
    result.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(name, None)
    # Native DLLs must come from the bundle or Windows, never the active venv PATH.
    windows = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="hfc-frozen-verification-") as folder:
        environment["HFC_DATA_DIR"] = str(Path(folder) / "profile")
        environment["MPLCONFIGDIR"] = str(Path(folder) / "matplotlib")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.run(
            [str(executable), "--self-test", str(result)],
            cwd=folder,
            env=environment,
            timeout=180,
            startupinfo=startup,
            capture_output=True,
        )
    if not result.is_file():
        raise RuntimeError(
            f"Frozen check produced no JSON; exit={process.returncode}; "
            f"stderr={process.stderr.decode(errors='replace')}"
        )
    outcome = json.loads(result.read_text(encoding="utf-8"))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    if process.returncode or not outcome.get("passed"):
        raise RuntimeError(f"Frozen check failed with exit code {process.returncode}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("result", type=Path)
    arguments = parser.parse_args()
    verify(arguments.executable, arguments.result)
