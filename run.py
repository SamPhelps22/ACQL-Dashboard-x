#!/usr/bin/env python3
"""ACQL Dashboard launcher.

Run this from the project root:

    python run.py

It checks for the packages listed in requirements.txt, installs any that are
missing into a local .venv, and then starts the dashboard. Nothing is installed
system-wide, so it is safe to run on a shared machine.

Most of the people who run this will never have opened a terminal before, and
this window is the only thing they see if something goes wrong. So it says
what it is doing in plain words, keeps pip's output to itself unless it fails
(at which point that output is the whole story), and every failure names the
thing to do next rather than the thing that broke.

Flags:
    --system      install into the current interpreter instead of a .venv
    --reinstall   force dependency reinstallation
    --rebuild     delete the .venv and build a fresh one
    --no-install  never install; fail if something is missing
    --check       report dependency status and exit without starting the UI
    --diagnose    print what the dashboard can see - every file it found,
                  every coach, every week - and exit. This is what to send
                  when a number looks wrong.
    --selfcheck   open the dashboard, photograph every page and tab, write a
                  report of anything that looks wrong, zip it into the data
                  folder's selfcheck folder, and close. This is what to send
                  when a page looks wrong.
    --verbose     show the commands being run and pip's own output
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
LAUNCHER_FLAGS = {
    "--system", "--reinstall", "--rebuild", "--no-install", "--check",
    "--diagnose", "--verbose",
}

# Set from the command line; controls whether the plumbing is shown.
VERBOSE = False


def say(message: str = "") -> None:
    """A line for whoever is watching. Flushed, because output is progress."""
    print(f"  {message}" if message else "", flush=True)


def detail(message: str) -> None:
    """A line for whoever is debugging. Only with --verbose."""
    if VERBOSE:
        print(f"    {message}", flush=True)


def wait_for_reader() -> None:
    """Hold a double-clicked window open long enough to read it.

    Started from Explorer rather than a terminal, the console closes the
    instant this process ends, taking the error with it. The launcher .bat
    pauses for exactly this reason; someone running run.py directly has no
    such help.
    """
    if os.name != "nt" or not sys.stdin.isatty():
        return
    try:
        input("  Press Enter to close this window. ")
    except (EOFError, KeyboardInterrupt):
        pass


def fail(message: str, *hint: str) -> NoReturn:
    print(f"\n  ACQL Dashboard could not start:\n    {message}", file=sys.stderr)
    for line in hint:
        print(f"    {line}", file=sys.stderr)
    print(file=sys.stderr)
    wait_for_reader()
    raise SystemExit(1)


def parse_requirements() -> list[tuple[str, str]]:
    """Return [(requirement_line, distribution_name)] from requirements.txt."""
    if not REQUIREMENTS.is_file():
        fail(f"requirements.txt is missing from {ROOT}.")
    out = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        # Options (-r, --index-url, -e ...) are pip's business, not packages.
        if not line or line.startswith("-"):
            continue
        name = line
        for sep in ("[", ">=", "<=", "==", "!=", "~=", ">", "<", ";", " "):
            name = name.split(sep, 1)[0]
        out.append((line, name.strip()))
    return out


def module_name(dist: str) -> str:
    return IMPORT_NAMES.get(dist, dist.replace("-", "_"))


def requirements_digest(python: str) -> str:
    """Identify the provisioned set: the requirements and the venv's Python.

    The venv's own interpreter version is what matters, not the launcher's.
    Keying on the launcher meant that running run.py under a different
    Python forced a full re-probe of an unchanged venv.
    """
    try:
        version = subprocess.run(
            [python, "-c", "import sys; print(sys.version)"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        version = ""
    return hashlib.sha256(REQUIREMENTS.read_bytes() + version.strip().encode()).hexdigest()


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_present() -> bool:
    """A venv exists here, working or not. pyvenv.cfg is written by every venv."""
    return (VENV_DIR / "pyvenv.cfg").is_file()


def running_inside_venv() -> bool:
    """Whether this very process is running from the project's .venv.

    Decided by sys.prefix, not by comparing executable paths. On macOS and
    Linux a venv's bin/python is a symlink to the system Python, so resolving
    the two paths makes them equal - and the launcher concluded it was
    already inside the venv when it was not, then imported the app outside
    it, where the packages it had just installed are not on the path.
    """
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return False
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def is_current_interpreter(target: str) -> bool:
    """Whether `target` is the interpreter already running this script."""
    if target == sys.executable:
        return True
    return target == str(venv_python()) and running_inside_venv()


def interpreter_works(python: str) -> bool:
    """Whether `python` actually starts.

    A venv records the path of the Python it was made from. Upgrade or remove
    that Python and the venv's interpreter still exists on disk but can no
    longer run - and every later step then fails with an error that looks
    like a missing package or a network problem.
    """
    try:
        return subprocess.run(
            [python, "-c", "pass"], capture_output=True, timeout=60
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probe(python: str, requirements: list[tuple[str, str]]) -> dict[str, str | None] | None:
    """Installed version for each distribution (None if missing).

    Returns None if the interpreter could not be run at all, which is a
    different problem from a package being missing and needs a different fix.
    """
    wanted = {dist: module_name(dist) for _, dist in requirements}
    script = (
        "import importlib.util, json, sys\n"
        "try:\n"
        "    from importlib.metadata import version, PackageNotFoundError\n"
        "except ImportError:\n"
        "    version = None\n"
        f"wanted = {json.dumps(wanted)}\n"
        "out = {}\n"
        "for dist, mod in wanted.items():\n"
        "    if importlib.util.find_spec(mod) is None:\n"
        "        out[dist] = None\n"
        "        continue\n"
        "    try:\n"
        "        out[dist] = version(dist) if version else '?'\n"
        "    except Exception:\n"
        "        out[dist] = '?'\n"
        "print(json.dumps(out))\n"
    )
    try:
        done = subprocess.run(
            [python, "-c", script], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def missing_packages(python: str, requirements: list[tuple[str, str]]) -> list[str]:
    """Names of distributions that `python` cannot import."""
    found = probe(python, requirements)
    if found is None:
        return [dist for _, dist in requirements]
    return [dist for dist, ver in found.items() if ver is None]


def pip_install(python: str, args: list[str]) -> bool:
    """Install, quietly. pip's output is kept back until it is worth reading.

    On a good run it is several hundred lines of wheels and hashes that mean
    nothing to the person waiting. On a bad one it is the only thing that
    says why - a company firewall, no network, a wheel that will not build -
    so it is printed in full at exactly that point.
    """
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", *args]
    detail(f"$ {Path(python).name} {' '.join(cmd[1:])}")
    if VERBOSE:
        return subprocess.run(cmd).returncode == 0
    try:
        done = subprocess.run(cmd, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as problem:
        say(f"Could not run pip: {problem}")
        return False
    if done.returncode != 0:
        say()
        say("pip could not install everything. Its own account of it:")
        say()
        for stream in (done.stdout, done.stderr):
            for line in (stream or "").strip().splitlines()[-25:]:
                print(f"      {line}", flush=True)
    return done.returncode == 0


def create_venv() -> bool:
    say(f"Making a private workspace for the dashboard's packages "
        f"({VENV_DIR.name}/), so nothing else on this computer is touched.")
    import importlib.util

    # Some slim distributions ship Python without the venv module.
    if importlib.util.find_spec("venv") is None:
        return False
    done = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if done.returncode != 0 or not venv_python().exists():
        return False
    pip_install(str(venv_python()), ["--upgrade", "pip", "--quiet"])
    return True


def remove_venv(reason: str) -> None:
    say(f"{reason} Building it again.")
    shutil.rmtree(VENV_DIR, ignore_errors=True)


def ensure_dependencies(argv: list[str]) -> str:
    """Return the interpreter that has every dependency available."""
    requirements = parse_requirements()
    reinstall = "--reinstall" in argv
    checking = "--check" in argv
    # A status report must not change anything: no venv built, nothing installed.
    no_install = "--no-install" in argv or checking
    use_system = "--system" in argv or os.environ.get("ACQL_NO_VENV") == "1"

    if not use_system:
        # --check never changes anything, so it overrides --rebuild rather than
        # deleting the venv and then declining to build a new one.
        if "--rebuild" in argv and not checking and VENV_DIR.exists():
            remove_venv("Rebuild requested.")
        # Presence is judged by pyvenv.cfg: when a venv's base Python is removed
        # on macOS or Linux, bin/python is left as a dangling symlink, which
        # exists() reports as missing - so the broken venv looked absent.
        elif venv_present() and not interpreter_works(str(venv_python())):
            # The Python this venv was built from has moved or been upgraded.
            if no_install:
                fail(
                    f"the {VENV_DIR.name}/ environment is broken - the Python it "
                    "was built from has changed or been removed.",
                    "Re-run without --no-install to rebuild it, or run with --rebuild.",
                )
            remove_venv("The virtual environment no longer runs (its Python changed).")

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
        target, use_system = sys.executable, True

    # A matching stamp means this exact requirements set was already installed.
    # --check always looks for itself: its whole job is to report the truth,
    # and a stamp only records what was true at the last install.
    digest = requirements_digest(target)
    if not (reinstall or use_system or checking) and STAMP.is_file():
        try:
            if STAMP.read_text(encoding="utf-8").strip() == digest:
                return target
        except OSError:
            pass

    if not interpreter_works(target):
        fail(
            f"the interpreter at {target} cannot be started.",
            "Run with --rebuild to recreate the environment.",
        )

    needed = [d for _, d in requirements] if reinstall else missing_packages(target, requirements)
    if needed:
        if no_install:
            fail(
                "missing packages: " + ", ".join(sorted(needed)),
                "Run  python run.py  (without --no-install or --check) to install them.",
            )
        first = not STAMP.is_file()
        say()
        say(f"Setting up {len(needed)} package{'' if len(needed) == 1 else 's'}: "
            f"{', '.join(sorted(needed))}")
        # Qt and matplotlib are the heavy ones; everything else is quick, and
        # promising a long wait for a small download is its own kind of wrong.
        heavy = any(
            d.lower().startswith(("pyside", "matplotlib", "numpy")) for d in needed
        )
        if first and heavy:
            say("This is the one-time setup. It downloads a few hundred megabytes")
            say("and can take several minutes. Nothing to do but wait.")
        elif first:
            say("This happens once. It should only take a moment.")
        say()
        wanted = [line for line, dist in requirements if reinstall or dist in needed]
        extra = ["--user"] if use_system and not running_inside_venv() else []
        ok = pip_install(target, wanted + extra)
        if not ok and extra:
            ok = pip_install(target, wanted)
        if not ok:
            fail(
                "the packages the dashboard needs could not be downloaded.",
                "Nearly always one of three things:",
                "  * this computer is offline - check the network and try again;",
                "  * a work or school network is blocking the download - try it",
                "    on a home connection;",
                "  * the download was interrupted - simply running it again",
                "    usually finishes the job, because what arrived is kept.",
            )
        still = missing_packages(target, requirements)
        if still:
            fail(
                "these packages installed but still cannot be loaded: "
                + ", ".join(sorted(still)) + ".",
                "Try:  python run.py --rebuild",
            )
        say("Setup finished.")

    if not use_system:
        try:
            STAMP.write_text(digest, encoding="utf-8")
        except OSError:
            pass
    return target


def blamed_file(exc: BaseException) -> tuple[Path, int, str] | None:
    """The project file an import actually failed in, and the line that failed.

    Python reports a bad relative import without naming the file, which is the
    one thing you need to fix it. The traceback knows, so this walks it and
    keeps the last frame that belongs to this project.
    """
    found: tuple[Path, int] | None = None
    here = Path(__file__).resolve()
    tb = exc.__traceback__
    while tb is not None:
        name = Path(tb.tb_frame.f_code.co_filename)
        try:
            full = name.resolve()
            inside = full == ROOT or ROOT in full.parents
        except (OSError, ValueError):
            full, inside = name, False
        if inside and full != here:
            found = (full, tb.tb_lineno)
        tb = tb.tb_next
    if found is None:
        return None
    path, line = found
    try:
        source = path.read_text(encoding="utf-8").splitlines()[line - 1].strip()
    except (OSError, IndexError, UnicodeDecodeError):
        source = ""
    return path, line, source


def explain_relative_import(exc: ImportError) -> tuple[str, str] | None:
    """A file sitting too high up the folder tree, named and placed.

    `from ...models import` only works from a file three folders below the
    project root. Put that file one folder too high and Python says the import
    went "beyond top-level package", which tells you nothing about which file
    or where it belongs. Both are worked out here instead.
    """
    blame = blamed_file(exc)
    if blame is None:
        return None
    path, line, source = blame
    match = re.match(r"from\s+(\.+)", source)
    if match is None:
        return None
    # One dot means "my own folder", each extra dot climbs one more, so a file
    # needs as many folders under the project root as the import has dots.
    needed = len(match.group(1))
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    depth = len(rel.parts) - 1                # folders it currently sits in
    if needed <= depth:
        return None
    short = " ".join(source.split()[:3])
    gap = needed - depth
    deeper = "one folder deeper" if gap == 1 else f"{gap} folders deeper"
    return (
        f"the project file {rel} is in the wrong folder.",
        f"Line {line} reads  {short} ...  which only works from a file "
        f"{needed} folder{'s' if needed != 1 else ''} below {ROOT.name}, "
        f"and this one is {depth}. Move {path.name} {deeper} "
        f"(pages belong in {Path('acql', 'ui', 'pages')}, widgets and theme "
        f"in {Path('acql', 'ui')}, everything else in acql).",
    )


def explain_import_error(exc: ImportError) -> tuple[str, str]:
    """Say what is actually missing: a project file, or an installed package.

    The two need opposite fixes. A missing package is solved by reinstalling;
    a missing project file is not, and telling someone to reinstall when a
    .py file is simply not where the code expects it sends them nowhere.
    """
    text = str(exc)
    # "attempted relative import beyond top-level package" - a project file
    # saved one folder too high. Nothing about it is a dependency problem, so
    # it has to be caught before the reinstall advice at the bottom.
    if "relative import" in text:
        placed = explain_relative_import(exc)
        if placed is not None:
            return placed
    # "cannot import name 'analytics' from 'acql' (...)" - a module the
    # project imports from one of its own packages is not in that folder.
    match = re.search(r"cannot import name '(\w+)' from '([\w.]+)'", text)
    if match and match.group(2).split(".")[0] == "acql":
        name, package = match.groups()
        where = Path(*package.split("."), f"{name}.py")
        return (
            f"the project file {where} is missing.",
            f"Put {name}.py in the {Path(*package.split('.'))} folder "
            f"(full path: {ROOT / where}).",
        )
    # "No module named 'acql.ui.pages.projections'" - same problem, one level up.
    missing = getattr(exc, "name", None) or ""
    if missing.split(".")[0] == "acql":
        where = Path(*missing.split(".")).with_suffix(".py")
        return (
            f"the project file {where} is missing.",
            f"Put it at {ROOT / where}.",
        )
    return (
        f"a required package could not be imported ({text}).",
        "The environment may be out of date. Try:  python run.py --reinstall",
    )


def report(target: str) -> None:
    """What --check prints: every requirement and the version installed."""
    requirements = parse_requirements()
    found = probe(target, requirements) or {}
    in_venv = target == str(venv_python())
    print(f"  Environment: {VENV_DIR.name + '/' if in_venv else 'system Python'}  ({target})")
    width = max((len(d) for _, d in requirements), default=0)
    for _, dist in requirements:
        print(f"    {dist:<{width}}  {found.get(dist) or 'MISSING'}")
    print("  Dependency check passed.")


SPREADSHEETS = ("*.xls", "*.xlsx", "*.xlsm")


def data_folders() -> list[Path]:
    """Where the dashboard looks for spreadsheets, without importing the app.

    The app settles this itself once it is running. The launcher only wants
    to know whether there is anything to read at all, and asking that question
    must not depend on the packages it may still be installing.
    """
    found = [ROOT, ROOT / "data"]
    return [folder for folder in found if folder.is_dir()]


def warn_if_no_data() -> None:
    """Say so before the dashboard opens empty.

    A new copy of the folder is often shared without the spreadsheets in it.
    The app comes up perfectly, shows nothing, and looks broken - when all it
    needs is the files.
    """
    for folder in data_folders():
        for pattern in SPREADSHEETS:
            for path in folder.glob(pattern):
                if not path.name.startswith("~$"):      # Excel's lock files
                    return
    say()
    say("No spreadsheets found, so the dashboard will open empty.")
    say(f"Put stats.xls and ACQL Dashboard.xlsx in:  {ROOT}")
    say("then press Refresh in the app - it will pick them up.")
    say()


def diagnose(target: str) -> int:
    """Print what the dashboard can see. The thing to send when a figure is wrong."""
    script = ROOT / "diag.py"
    if script.is_file():
        return subprocess.run([target, str(script)], cwd=str(ROOT)).returncode
    say("diag.py is not in this folder, so there is nothing to report with.")
    return 1


def main() -> int:
    global VERBOSE
    argv = sys.argv[1:]
    VERBOSE = "--verbose" in argv
    if sys.version_info < MIN_PYTHON:
        fail(
            f"this needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer, "
            f"and this computer has {sys.version.split()[0]}.",
            "Install a current Python from python.org and try again.",
            "On the first screen of the installer, tick "
            '"Add python.exe to PATH".',
        )

    say(f"ACQL Dashboard  ({ROOT})")
    target = ensure_dependencies(argv)

    if "--check" in argv:
        report(target)
        return 0

    if "--diagnose" in argv:
        return diagnose(target)

    warn_if_no_data()

    forward = [a for a in argv if a not in LAUNCHER_FLAGS]
    launch = ["-m", "acql.ui.app", *forward]

    # Already in the right interpreter: import directly so Ctrl-C and the exit
    # code behave normally. Otherwise hand off to the venv interpreter.
    if is_current_interpreter(target):
        say("Starting the dashboard. The window opens in a few seconds.")
        sys.path.insert(0, str(ROOT))
        try:
            from acql.ui.app import main as app_main
        except ImportError as exc:
            fail(*explain_import_error(exc))
        return app_main(forward)

    say("Starting the dashboard. The window opens in a few seconds.")
    try:
        code = subprocess.run([target, *launch], cwd=str(ROOT)).returncode
    except KeyboardInterrupt:
        # The child has the same Ctrl-C and shuts itself down; the launcher
        # just needs to leave quietly rather than print a traceback over it.
        return 130
    if code:
        say()
        say("The dashboard stopped unexpectedly. Whatever is printed above is")
        say("the reason - send Sam a photo of this window.")
        wait_for_reader()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
