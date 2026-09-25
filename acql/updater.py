"""Installing an update: one zip, a backup first, and a way back.

An update arrives as one file - ACQL-Dashboard-<version>-update.zip - with
the new code laid out the way the project folder is, and a manifest that
lists every file in it with a fingerprint. Installing it:

  1. backs up the code that is there now (not the data - the update never
     touches the data folder) into backups/code-<version>-<time>.zip;
  2. copies the new files in, retrying a file OneDrive has open for a moment;
  3. checks every file landed whole, and that the app still starts;
  4. if either check fails, puts the backup straight back.

The files the update doesn't carry - config.py, names.py and the like, which
only exist on this computer - are left exactly as they are.

This module only uses the standard library and never imports the rest of
the app, so the installer can load it straight out of an update that hasn't
been installed yet, with whatever Python is to hand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = "manifest.json"
PAYLOAD = "payload"
BACKUPS = "backups"
UPDATE_NAME = re.compile(r"ACQL[-_ ]Dashboard[-_ ](\d+(?:\.\d+)*)[-_ ]update\.zip$", re.IGNORECASE)
#: Folders a code backup leaves out: the data, earlier backups, the packages.
NOT_CODE = {".venv", "venv", "data", BACKUPS, "__pycache__", ".git", "selfcheck"}
COPY_ATTEMPTS = 5
COPY_WAIT_S = 1.5


class UpdateError(Exception):
    """An update that couldn't be installed, in words fit to show."""


class RollbackIncomplete(UpdateError):
    """Putting the previous version back didn't finish - says which files, and where the backup is."""

    def __init__(self, backup: Path, failed: list[str], reason: str = "") -> None:
        self.backup, self.failed = backup, failed
        shown = ", ".join(failed[:6]) + (f" and {len(failed) - 6} more" if len(failed) > 6 else "")
        super().__init__(
            (f"{reason} " if reason else "")
            + f"Putting the previous version back didn't finish: {shown} couldn't be "
            f"written (something has them open). Close the dashboard and anything "
            f"else using the folder, then run the installer again with --undo, or "
            f"unzip {backup.name} from the backups folder over the dashboard's folder."
        )


# ---- versions ------------------------------------------------------------------
def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", str(text))[:4]) or (0,)


def installed_version(root: Path) -> str:
    """The version the project folder says it is, or "" for one from before 2.0."""
    path = Path(root) / "acql" / "version.py"
    try:
        found = re.search(r'VERSION\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    return found.group(1) if found else ""


# ---- finding the project and the update --------------------------------------------
def is_project(folder: Path) -> bool:
    folder = Path(folder)
    return (folder / "run.py").is_file() and (folder / "acql").is_dir()


def likely_projects(start: Path | None = None) -> list[Path]:
    """Where the dashboard is probably installed, best guess first."""
    seen, out = set(), []
    home = Path.home()
    candidates = []
    if start is not None:
        start = Path(start).resolve()
        candidates += [start, *start.parents]
    for base in (home / "OneDrive" / "Documents", home / "Documents", home / "OneDrive",
                 home / "Desktop", home):
        candidates.append(base / "Code x")
    for path in candidates:
        try:
            key = path.resolve()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        if is_project(key):
            out.append(key)
    return out


def find_update_zips(folders: list[Path] | None = None) -> list[tuple[str, Path]]:
    """(version, path) for every update zip in the usual places, newest version first."""
    folders = folders or [Path.home() / "Downloads", Path.home() / "OneDrive" / "Downloads",
                          Path.home() / "Desktop"]
    found = []
    for folder in folders:
        try:
            entries = list(Path(folder).iterdir())
        except OSError:
            continue
        for path in entries:
            match = UPDATE_NAME.search(path.name)
            if match and path.is_file():
                found.append((match.group(1), path))
    found.sort(key=lambda vp: (version_tuple(vp[0]), vp[1].stat().st_mtime), reverse=True)
    return found


# ---- reading an update --------------------------------------------------------------
@dataclass
class Update:
    version: str
    files: dict[str, str]                 # relative path -> sha256
    remove: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    notes: str = ""
    source: Path | None = None            # the zip, or the unpacked folder

    def read(self, rel: str) -> bytes:
        if self.source is None:
            raise UpdateError("The update has no files.")
        if self.source.is_dir():
            return (self.source / PAYLOAD / rel).read_bytes()
        with zipfile.ZipFile(self.source) as zf:
            prefix = _zip_prefix(zf)
            return zf.read(f"{prefix}{PAYLOAD}/{rel}")


def _zip_prefix(zf: zipfile.ZipFile) -> str:
    """Updates are zipped inside one top folder; find it."""
    for name in zf.namelist():
        if name.endswith(MANIFEST):
            return name[: -len(MANIFEST)]
    raise UpdateError("That zip isn't an ACQL Dashboard update - it has no manifest.")


def open_update(source: str | Path) -> Update:
    """Read an update from its zip, or from the folder it was unzipped to."""
    source = Path(source)
    try:
        if source.is_dir():
            raw = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
        else:
            with zipfile.ZipFile(source) as zf:
                raw = json.loads(zf.read(_zip_prefix(zf) + MANIFEST).decode("utf-8"))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"Couldn't read the update ({exc}).") from exc
    return Update(
        version=str(raw.get("version", "")),
        files=dict(raw.get("files", {})),
        remove=list(raw.get("remove", [])),
        requires=list(raw.get("requires", [])),
        notes=str(raw.get("notes", "")),
        source=source,
    )


# ---- backing up and putting back -----------------------------------------------------
def backup_code(root: Path, label: str) -> Path:
    """Zip every code file in the project (never the data) into backups/."""
    root = Path(root)
    folder = root / BACKUPS
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"code-{label}-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _code_files(root):
            zf.write(path, path.relative_to(root).as_posix())
    return target


def _code_files(root: Path):
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root)
        if any(part in NOT_CODE for part in rel.parts[:-1]) or rel.parts[0] in NOT_CODE:
            continue
        if path.is_file() and (path.suffix in (".py", ".bat", ".txt", ".json", ".csv", ".ico", ".png", ".spec", ".html")
                               or path.name == "requirements.txt"):
            # the app's own memory and settings are data, wherever they sit
            if rel.parts[0] != "acql" and path.suffix in (".json", ".csv", ".png") and len(rel.parts) == 1:
                continue
            yield path


def restore_backup(root: Path, backup: Path, *, remove: list[str] = ()) -> None:
    """Put a code backup back: its files over the top, and `remove` taken away.

    Files that already match the backup are left alone, and one file that
    can't be written doesn't stop the rest: everything that can go back does,
    and then RollbackIncomplete names what couldn't.
    """
    root = Path(root)
    failed: list[str] = []
    with zipfile.ZipFile(backup) as zf:
        names = set(zf.namelist())
        for name in sorted(names):
            target = root / name
            data = zf.read(name)
            try:
                if target.is_file() and _sha(target.read_bytes()) == _sha(data):
                    continue
            except OSError:
                pass
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_with_retry(target, data)
            except (OSError, UpdateError):
                failed.append(name)
        # Only take away the update's new files once the old ones are back,
        # so a half-finished rollback never leaves a module missing that the
        # restored code doesn't need anyway.
        for rel in remove:
            if rel in names:
                continue
            try:
                (root / rel).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                failed.append(rel)
    if failed:
        raise RollbackIncomplete(backup, failed)


def latest_backup(root: Path) -> Path | None:
    found = sorted((Path(root) / BACKUPS).glob("code-*.zip"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


# ---- installing ------------------------------------------------------------------------
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_with_retry(target: Path, data: bytes) -> None:
    """Write via a temporary file and a rename, so a file is never half-written."""
    last = None
    tmp = target.with_name(target.name + ".new")
    for attempt in range(COPY_ATTEMPTS):
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
            return
        except OSError as exc:            # OneDrive or an editor holding the file
            last = exc
            time.sleep(COPY_WAIT_S * (attempt + 1))
    try:
        tmp.unlink()
    except OSError:
        pass
    raise UpdateError(f"Couldn't write {target.name} ({last}). Close anything that has it open and try again.")


@dataclass
class Installed:
    version: str
    backup: Path
    written: list[str]
    removed: list[str]
    missing_own: list[str]            # files this computer should have and doesn't


def install(update: Update, root: Path, *, check=None, say=print,
            allow_same: bool = False) -> Installed:
    """Install `update` into the project at `root`. Rolls back if anything fails.

    `check(root)` is run after copying and must return "" if the app still
    starts, or the reason it doesn't. The default imports the app in a fresh
    Python. An update that isn't newer than what is installed is refused
    unless `allow_same` - reinstalling over itself would otherwise leave
    "undo" pointing at the same version.
    """
    root = Path(root)
    if not is_project(root):
        raise UpdateError(f"{root} doesn't look like the dashboard's folder (no run.py and acql folder).")
    current = installed_version(root)
    if current and not allow_same and version_tuple(update.version) <= version_tuple(current):
        raise UpdateError(
            f"Version {current} is already installed, and this update is {update.version}."
        )
    for rel, digest in update.files.items():
        if _sha(update.read(rel)) != digest:
            raise UpdateError(f"The update's copy of {rel} is damaged - download it again.")

    before = installed_version(root) or "1.x"
    say(f"Backing up the current code (version {before})...")
    backup = backup_code(root, before.replace(".", "_"))
    say(f"  saved as {backup.relative_to(root)}")

    new_files = [rel for rel in update.files if not (root / rel).exists()]
    written, removed = [], []
    try:
        say(f"Copying in {len(update.files)} files...")
        for rel in sorted(update.files):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_with_retry(target, update.read(rel))
            written.append(rel)
        for rel in update.remove:
            path = root / rel
            if path.is_file():
                path.unlink()
                removed.append(rel)
        for rel, digest in update.files.items():
            if _sha((root / rel).read_bytes()) != digest:
                raise UpdateError(f"{rel} didn't copy cleanly.")
        say("Checking the dashboard still starts...")
        problem = (check or check_starts)(root)
        if problem:
            raise UpdateError(f"The new version wouldn't start: {problem}")
    except BaseException as exc:          # Ctrl+C during the check too
        say("Something went wrong - putting the previous version back.")
        try:
            restore_backup(root, backup, remove=new_files)
        except RollbackIncomplete as incomplete:
            raise RollbackIncomplete(incomplete.backup, incomplete.failed,
                                     reason=f"The update failed ({exc}).") from exc
        if isinstance(exc, UpdateError):
            raise
        if not isinstance(exc, Exception):
            raise
        raise UpdateError(str(exc)) from exc

    missing = [rel for rel in update.requires if not (root / rel).exists()]
    previous = last_install(root)
    if previous and before == update.version:
        # The same version put in again: the way back is still the version
        # before that, so the record that points to it stays.
        pass
    else:
        record = {
            "version": update.version, "from": before, "at": time.time(),
            "backup": backup.name, "added": new_files, "removed": removed,
        }
        try:
            (root / BACKUPS / LAST_INSTALL).write_text(json.dumps(record, indent=1), encoding="utf-8")
        except OSError:
            pass
    return Installed(update.version, backup, written, removed, missing)


LAST_INSTALL = "last-install.json"


def last_install(root: Path) -> dict | None:
    try:
        return json.loads((Path(root) / BACKUPS / LAST_INSTALL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def undo_last(root: Path) -> str:
    """Put back the code from before the last update. Returns the version restored."""
    root = Path(root)
    record = last_install(root)
    if not record:
        raise UpdateError("There's no update to undo - nothing has been installed with this updater.")
    backup = root / BACKUPS / record.get("backup", "")
    if not backup.is_file():
        raise UpdateError(f"The backup {backup.name} isn't in the backups folder any more.")
    restore_backup(root, backup, remove=list(record.get("added", [])))
    try:
        (root / BACKUPS / LAST_INSTALL).unlink()
    except OSError:
        pass
    return str(record.get("from", ""))


def project_python(root: Path) -> str:
    """The Python the dashboard runs under: its own .venv if there is one."""
    root = Path(root)
    for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def check_starts(root: Path) -> str:
    """Import the whole app in a fresh Python without opening a window."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import acql.ui.app as app;"
        "print('ok', len(app.PAGE_CLASSES))"
    )
    try:
        done = subprocess.run(
            [project_python(root), "-c", code, str(root)],
            cwd=str(root), capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"couldn't run Python ({exc})"
    if done.returncode == 0 and done.stdout.strip().startswith("ok"):
        return ""
    lines = [line for line in (done.stderr or done.stdout).strip().splitlines() if line.strip()]
    return lines[-1] if lines else f"exit code {done.returncode}"
