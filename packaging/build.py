#!/usr/bin/env python3
"""Build the standalone executable for whichever platform this is run on.

    python packaging/build.py

Installs PyInstaller and the app's dependencies if they are missing, then
writes the executable to dist/. Windows produces "ACQL Dashboard.exe", macOS
"ACQL Dashboard.app", Linux a plain "ACQL Dashboard" binary.

A build only ever produces a binary for the platform it runs on - PyInstaller
cannot cross-compile. Use the GitHub Actions workflow to get all three.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "acql.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run(args: list[str]) -> None:
    print(f"  $ {' '.join(args)}")
    if subprocess.run(args, cwd=str(ROOT)).returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(args)}")


def main() -> int:
    print(f"  Building the ACQL Dashboard for {sys.platform}\n")

    run([
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "-r", str(ROOT / "requirements.txt"), "pyinstaller>=6.0",
    ])

    for stale in (DIST, BUILD):
        if stale.exists():
            print(f"  Removing {stale.name}/")
            shutil.rmtree(stale, ignore_errors=True)

    run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"])

    produced = sorted(p for p in DIST.iterdir()) if DIST.is_dir() else []
    if not produced:
        raise SystemExit("The build produced nothing in dist/.")

    print("\n  Built:")
    for item in produced:
        size = _size(item)
        print(f"    {item.name}{f'  ({size})' if size else ''}")

    # The app reads spreadsheets from a data/ folder beside the executable.
    data_dir = DIST / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "PUT YOUR SPREADSHEETS HERE.txt").write_text(
        "Drop each week's stats.xls and the updated ACQL Dashboard.xlsx into\n"
        "this folder, then press Refresh in the app.\n",
        encoding="utf-8",
    )
    print(f"\n  Ship the contents of {DIST}.")
    return 0


def _size(path: Path) -> str:
    try:
        total = (
            path.stat().st_size
            if path.is_file()
            else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        )
    except OSError:
        return ""
    return f"{total / 1_048_576:.0f} MB"


if __name__ == "__main__":
    raise SystemExit(main())
