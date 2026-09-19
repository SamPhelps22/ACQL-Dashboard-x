#!/usr/bin/env python3
"""ACQL Dashboard launcher.

Run this from the project root:

    python run.py

It checks for the packages listed in requirements.txt, installs any that are
missing into a local .venv, and then starts the dashboard. Nothing is installed
system-wide, so it is safe to run on a shared machine.

Flags:
    --system      install into the current interpreter instead of a .venv
    --reinstall   force dependency reinstallation
    --no-install  never install; fail if something is missing
    --check       report dependency status and exit without starting the UI
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

MIN_PYTHON = (3, 9)
ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
VENV_DIR = ROOT / ".venv"
# Distribution name -> module name to probe, where the two differ.
IMPORT_NAMES = {"PySide6": "PySide6", "xlrd": "xlrd", "openpyxl": "openpyxl"}
# Marker records which requirements set the venv was last provisioned against,
# so a normal launch costs one file read rather than a pip round-trip.
STAMP = VENV_DIR / ".acql-deps-stamp"


def fail(message: str, *hint: str) -> NoReturn:
    print(f"\n  ACQL Dashboard could not start:\n    {message}", file=sys.stderr)
    for line in hint:
        print(f"    {line}", file=sys.stderr)
    print(file=sys.stderr)
    raise SystemExit(1)


def parse_requirements() -> list[tuple[str, str]]:
    """Return [(requirement_line, distribution_name)] from requirements.txt."""
    if not REQUIREMENTS.is_file():
        fail(f"requirements.txt is missing from {ROOT}.")
    out = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line
        for sep in ("[", ">=", "<=", "==", "!=", "~=", ">", "<", ";"):
            name = name.split(sep, 1)[0]
        out.append((line, name.strip()))
    return out


def requirements_digest() -> str:
    payload = REQUIREMENTS.read_bytes() + sys.version.encode()
    return hashlib.sha256(payload).hexdigest()


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def running_inside_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == venv_python().resolve()
    except OSError:
        return False


def missing_packages(python: str, requirements: list[tuple[str, str]]) -> list[str]:
    """Names of distributions that `python` cannot import."""
    modules = [IMPORT_NAMES.get(dist, dist.replace("-", "_")) for _, dist in requirements]
    probe = (
        "import importlib.util,sys;"
        f"mods={modules!r};"
        "print('\\n'.join(m for m in mods "
        "if importlib.util.find_spec(m) is None))"
    )
    try:
        done = subprocess.run(
            [python, "-c", probe], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return [dist for _, dist in requirements]
    if done.returncode != 0:
        return [dist for _, dist in requirements]
    found = {line.strip() for line in done.stdout.splitlines() if line.strip()}
    reverse = {IMPORT_NAMES.get(d, d.replace("-", "_")): d for _, d in requirements}
    return [reverse[m] for m in found if m in reverse]


def pip_install(python: str, args: list[str]) -> bool:
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", *args]
    print(f"  $ {' '.join(cmd[1:])}")
    return subprocess.run(cmd).returncode == 0


def create_venv() -> bool:
    print(f"  Creating a virtual environment in {VENV_DIR.name}/ ...")
    import importlib.util

    # Some slim distributions ship Python without the venv module.
    if importlib.util.find_spec("venv") is None:
        return False
    done = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if done.returncode != 0 or not venv_python().exists():
        return False
    pip_install(str(venv_python()), ["--upgrade", "pip", "--quiet"])
    return True


def ensure_dependencies(argv: list[str]) -> str:
    """Return the interpreter that has every dependency available."""
    requirements = parse_requirements()
    reinstall = "--reinstall" in argv
    no_install = "--no-install" in argv
    use_system = "--system" in argv or os.environ.get("ACQL_NO_VENV") == "1"

    if use_system:
        target = sys.executable
    else:
        if not venv_python().exists() and not no_install:
            if not create_venv():
                print(
                    "  Could not create a virtual environment "
                    "(python3-venv may not be installed); "
                    "falling back to the current interpreter."
                )
                use_system = True
        target = sys.executable if use_system else str(venv_python())
        if not use_system and not Path(target).exists():
            target = sys.executable
            use_system = True

    # A matching stamp means this exact requirements set was already installed.
    digest = requirements_digest()
    if not reinstall and not use_system and STAMP.is_file():
        try:
            if STAMP.read_text(encoding="utf-8").strip() == digest:
                return target
        except OSError:
            pass

    needed = [d for _, d in requirements] if reinstall else missing_packages(target, requirements)
    if needed:
        if no_install:
            fail(
                "missing packages: " + ", ".join(sorted(needed)),
                "Re-run without --no-install to let the launcher install them.",
            )
        print(f"  Installing {len(needed)} package(s): {', '.join(sorted(needed))}")
        wanted = [line for line, dist in requirements if reinstall or dist in needed]
        extra = ["--user"] if use_system and not running_inside_venv() else []
        ok = pip_install(target, wanted + extra)
        if not ok and extra:
            ok = pip_install(target, wanted)
        if not ok:
            fail(
                "dependency installation failed.",
                "Check your network connection, then try:",
                f"    {target} -m pip install -r requirements.txt",
            )
        still = missing_packages(target, requirements)
        if still:
            fail("these packages are still unavailable: " + ", ".join(sorted(still)))
        print("  All dependencies are ready.")

    if not use_system:
        try:
            STAMP.write_text(digest, encoding="utf-8")
        except OSError:
            pass
    return target


def main() -> int:
    argv = sys.argv[1:]
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, "
            f"but this is {sys.version.split()[0]}."
        )

    print(f"  ACQL Dashboard  ({ROOT})")
    target = ensure_dependencies(argv)

    if "--check" in argv:
        print("  Dependency check passed.")
        return 0

    forward = [a for a in argv if a not in {"--system", "--reinstall", "--no-install", "--check"}]
    launch = ["-m", "acql.ui.app", *forward]

    # Already in the right interpreter: import directly so Ctrl-C and the exit
    # code behave normally. Otherwise hand off to the venv interpreter.
    if Path(target).resolve() == Path(sys.executable).resolve():
        sys.path.insert(0, str(ROOT))
        from acql.ui.app import main as app_main

        return app_main(forward)

    return subprocess.run([target, *launch], cwd=str(ROOT)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
