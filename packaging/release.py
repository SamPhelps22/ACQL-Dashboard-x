#!/usr/bin/env python3
"""Make a release the dashboard can update itself from.

    python packaging/release.py --since <commit> --notes "What changed"
    python packaging/release.py --check          (build and test-install only; write nothing)

Writes two files into updates/ - the update zip and latest.json, which names
it and carries its SHA-256. The dashboard asks the repository's default
branch for updates/latest.json (acql/autoupdate.py), so a release is
published by committing updates/ and pushing it there. Nothing here pushes.

What goes in the zip is the code as it was last committed (never the working
folder, so nothing half-finished and nothing git ignores can get in): the
acql package, the tests, the packaging scripts, and the handful of files that
start it. No data, no spreadsheets, no settings.

`--since` is the commit the last release was made from: any file the zip
carried then and git has since deleted or moved is listed for removal, so a
module that moved does not leave its old copy behind. Without it, the commit
that last changed updates/latest.json is used; with no release yet, nothing
is removed.

Before anything is written, the zip is installed into a scratch copy of the
project as it stood at `--since` and that copy is started - the same check
the installer makes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import autoupdate, updater  # noqa: E402

#: What an update carries: these folders whole, and these files.
FOLDERS = ("acql/", "tests/", "packaging/")
FILES = ("run.py", "requirements.txt", "ACQL Dashboard.bat", "schedule.ps1", "START HERE.txt", "README.md",
         "diag.py")
OUT = ROOT / autoupdate.FOLDER


def git(*args: str, binary: bool = False):
    done = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(ROOT), capture_output=True)
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout if binary else done.stdout.decode("utf-8")


def carried(path: str) -> bool:
    return path in FILES or path.startswith(FOLDERS)


def tracked(commit: str) -> list[str]:
    return [p for p in git("ls-tree", "-r", "--name-only", "-z", commit).split("\0") if p and carried(p)]


def version_at(commit: str) -> str:
    import re
    found = re.search(r'VERSION\s*=\s*"([^"]+)"', git("show", f"{commit}:acql/version.py"))
    if not found:
        raise SystemExit("acql/version.py has no VERSION")
    return found.group(1)


def last_release() -> str:
    """The commit the last release was made from, or "" when there has been none."""
    found = git("log", "-1", "--format=%H", "--", f"{autoupdate.FOLDER}/{autoupdate.MANIFEST}").strip()
    if not found:
        return ""
    try:
        made_from = json.loads(git("show", f"{found}:{autoupdate.FOLDER}/{autoupdate.MANIFEST}")).get("commit", "")
    except ValueError:
        made_from = ""
    return made_from or found


def build(commit: str, since: str, notes: str) -> tuple[str, bytes]:
    """(the zip's name, its bytes) for the code at `commit`."""
    version = version_at(commit)
    paths = tracked(commit)
    gone = sorted(set(tracked(since)) - set(paths)) if since else []
    files, buffer = {}, io.BytesIO()
    top = f"ACQL-Dashboard-{version}-update"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in paths:
            data = git("show", f"{commit}:{path}", binary=True)
            files[path] = hashlib.sha256(data).hexdigest()
            info = zipfile.ZipInfo(f"{top}/{updater.PAYLOAD}/{path}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
        manifest = {"version": version, "files": files, "remove": gone, "requires": [], "notes": notes,
                    "commit": commit}
        info = zipfile.ZipInfo(f"{top}/{updater.MANIFEST}", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, json.dumps(manifest, indent=1))
    return f"{top}.zip", buffer.getvalue()


def try_it(name: str, body: bytes, since: str, commit: str) -> None:
    """Install the zip over the project as it stood at `since` (or at `commit`
    for a first release), and start it - in a scratch folder."""
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        zipped = scratch / name
        zipped.write_bytes(body)
        project = scratch / "project"
        project.mkdir()
        start = since or commit
        with zipfile.ZipFile(io.BytesIO(git("archive", "--format=zip", start, binary=True))) as zf:
            zf.extractall(project)
        update = updater.open_update(zipped)
        before = updater.installed_version(project)
        python = sys.executable
        real = updater.project_python
        updater.project_python = lambda root: python          # the scratch copy has no .venv of its own
        try:
            done = updater.install(update, project, say=lambda text: print(f"    {text}"), allow_same=True)
        finally:
            updater.project_python = real
        after = updater.installed_version(project)
        left = [rel for rel in update.remove if (project / rel).exists()]
        if after != update.version or left:
            raise SystemExit(f"test install went wrong: version {after}, left behind {left[:5]}")
        wrong = [rel for rel, digest in update.files.items()
                 if hashlib.sha256((project / rel).read_bytes()).hexdigest() != digest]
        if wrong:
            raise SystemExit(f"test install: {len(wrong)} files differ, e.g. {wrong[:3]}")
        print(f"  Test install: {before} -> {after}, {len(update.files)} files in place, "
              f"{len(update.remove)} old ones removed, and it starts. ({getattr(done, 'backup', '')})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default="", help="the commit the last release was made from")
    parser.add_argument("--notes", default="", help="what changed, in a sentence or two")
    parser.add_argument("--commit", default="HEAD", help="the commit to release (default: HEAD)")
    parser.add_argument("--check", action="store_true", help="build and test-install, write nothing")
    args = parser.parse_args()

    commit = git("rev-parse", args.commit).strip()
    since = git("rev-parse", args.since).strip() if args.since else last_release()
    version = version_at(commit)
    if since and updater.version_tuple(version) <= updater.version_tuple(version_at(since)) and not args.check:
        raise SystemExit(f"The version is still {version}, as it was at the last release: raise it in "
                         "acql/version.py and commit that first.")
    print(f"  Releasing {version} from {commit[:7]}" + (f", since {since[:7]}" if since else " (the first release)"))
    name, body = build(commit, since, args.notes)
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(body)).read(name[:-4] + "/" + updater.MANIFEST))
    print(f"  {name}: {len(body) / 1024:.0f} KB, {len(manifest['files'])} files, "
          f"{len(manifest['remove'])} to remove")
    try_it(name, body, since, commit)
    if args.check:
        print("  Check only: nothing written.")
        return 0
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("ACQL-Dashboard-*-update.zip"):
        old.unlink()                                  # one release is kept: the newest
    (OUT / name).write_bytes(body)
    latest = autoupdate.manifest_for(OUT / name, version, args.notes)
    latest["commit"] = commit
    (OUT / autoupdate.MANIFEST).write_text(json.dumps(latest, indent=1) + "\n", encoding="utf-8")
    print(f"  Written: {autoupdate.FOLDER}/{name} and {autoupdate.FOLDER}/{autoupdate.MANIFEST}")
    print("  To publish: commit the updates folder and push it to the repository's default branch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
