"""A locked copy of the pool's data, so GitHub can send the emails and texts
while this PC is off.

The PC packs the database and the pick/standings spreadsheets into one file,
locks it with a key only this PC and GitHub's secrets hold, and uploads it as
a download on the pool website's repository (a release called "vault"). The
"ACQL cloud mail" workflow downloads it, unlocks it, refreshes the lines and
sends the card, the Sunday brief and the deadline texts.

Passwords and tokens are taken out before packing: GitHub gets the Gmail and
Odds API keys from its own secrets.

    python -m acql.site.snapshot --new-key     make the key, copy it to the clipboard
    python -m acql.site.snapshot --copy-key    copy the key again
    python -m acql.site.snapshot --upload      pack and upload now
    python -m acql.site.snapshot --cloud-on    GitHub sends from now on (this PC stops)
    python -m acql.site.snapshot --cloud-off   this PC sends again
    python -m acql.site.snapshot --status

The lock: BLAKE2b (keyed) as a counter-mode stream, then HMAC-SHA256 over the
whole file - standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

MAGIC = b"ACQLV1"
TAG = "vault"
KIND, KEY = "settings", "cloud"
#: The PC uploads at most this often (each run of the scheduled job asks).
EVERY = 50 * 60
TIMEOUT = 60
#: Folders under data/ that the emails never read (or that are big and rebuilt).
SKIP_DIRS = {"backups", "updates", "site-preview", "logos", "recaps", "selfcheck",
             "runs", "snapshots", "__pycache__"}
SKIP_FILES = {"acql.db", "acql-log.txt", "headless.lock", "acql-email.json",
              "acql-odds.json", "acql-cards.json"}
#: What the cloud runs write, carried from one run to the next (GitHub's cache).
CARRIED = ("alerts", "cardmail", "cloudrun")
#: The PC's own schedule (schedule.ps1), kept by GitHub's hourly run: (weekdays Mon=0, from, until).
JOBS = {"email": ((1, 2, 3), 12, 20), "brief": ((6,), 9, 13)}


class SnapshotError(Exception):
    """Something to show the person, in plain English."""


def in_cloud() -> bool:
    return os.environ.get("ACQL_CLOUD") == "1"


# ---- the lock ---------------------------------------------------------------
def _keys(master: bytes) -> tuple[bytes, bytes]:
    return (hashlib.blake2b(b"enc", key=master, digest_size=32).digest(),
            hashlib.blake2b(b"mac", key=master, digest_size=32).digest())


def _stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    pad = bytearray()
    for n in range((len(data) + 63) // 64):
        pad += hashlib.blake2b(nonce + n.to_bytes(8, "big"), key=key, digest_size=64).digest()
    size = len(data)
    return (int.from_bytes(data, "big") ^ int.from_bytes(bytes(pad[:size]), "big")).to_bytes(size, "big")


def lock(plain: bytes, master: bytes, *, nonce: bytes | None = None) -> bytes:
    enc, mac = _keys(master)
    nonce = nonce or secrets.token_bytes(16)
    body = MAGIC + nonce + _stream(enc, nonce, plain)
    return body + hmac.new(mac, body, hashlib.sha256).digest()


def unlock(blob: bytes, master: bytes) -> bytes:
    enc, mac = _keys(master)
    body, tag = blob[:-32], blob[-32:]
    if not body.startswith(MAGIC) or len(blob) < len(MAGIC) + 48:
        raise SnapshotError("that isn't a pool snapshot")
    if not hmac.compare_digest(tag, hmac.new(mac, body, hashlib.sha256).digest()):
        raise SnapshotError("the snapshot key doesn't match (or the file is damaged)")
    nonce = body[len(MAGIC):len(MAGIC) + 16]
    return _stream(enc, nonce, body[len(MAGIC) + 16:])


def parse_key(text: str) -> bytes:
    text = "".join(text.split())
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise SnapshotError("the snapshot key should be 64 letters and digits (0-9, a-f)")
    return raw


# ---- the PC's settings ------------------------------------------------------
def _settings() -> dict:
    from .. import store
    raw = store.get(KIND, KEY, {})
    return dict(raw) if isinstance(raw, dict) else {}


def _save(values: dict) -> None:
    from .. import store
    store.put(KIND, KEY, values)


def master_key() -> bytes:
    if in_cloud():
        return parse_key(os.environ.get("ACQL_SNAPSHOT_KEY", ""))
    from .mailer import unseal
    sealed = _settings().get("sealed_key", "")
    if not sealed:
        raise SnapshotError("no snapshot key yet - run: python -m acql.site.snapshot --new-key")
    return parse_key(unseal(sealed))


def cloud_sends() -> bool:
    """True when GitHub sends the emails and texts, so this PC must not."""
    try:
        return bool(_settings().get("sending"))
    except Exception:  # noqa: BLE001 - unsure means the PC sends, as before
        return False


def pc_should_skip(what: str) -> bool:
    """For headless.py: the PC leaves `what` to GitHub when cloud sending is on."""
    if in_cloud():
        return False
    try:
        if cloud_sends():
            from ..ui.pages.base import write_log
            write_log(f"headless: {what} left to GitHub (cloud sending is on)")
            return True
    except Exception:  # noqa: BLE001 - unsure means the PC sends, as before
        pass
    return False


# ---- packing ----------------------------------------------------------------
def _db_copy(target: Path) -> None:
    """A consistent copy of the database with every sealed secret blanked."""
    from .. import store
    source = sqlite3.connect(f"file:{store.db_path()}?mode=ro", uri=True)
    dest = sqlite3.connect(str(target))
    try:
        source.backup(dest)
    finally:
        source.close()
    dest.close()
    store.use(target)
    try:
        # every sealed value in the settings (Gmail, website token, private page, this key)
        for key, value in store.items("settings").items():
            if isinstance(value, dict) and any(f.startswith("sealed_") and value[f] for f in value):
                store.put("settings", key, {f: ("" if f.startswith("sealed_") else v) for f, v in value.items()})
        if store.items("odds").get("key"):
            store.put("odds", "key", "")
    finally:
        store.use(None)
    # rewrite the file so the blanked values don't linger in its free space
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM")
    finally:
        conn.close()
    if b"dpapi:" in target.read_bytes() or b"plain:" in target.read_bytes():
        raise SnapshotError("a sealed value was still in the copy - nothing uploaded")


def _sheets() -> list[Path]:
    """Every spreadsheet the season is read from, wherever it sits."""
    from ..config import Settings
    from ..repository import discover
    return [Path(s.path) for s in discover(Settings.load().search_paths())]


def pack() -> bytes:
    from ..config import DATA_DIR, ROOT, SETTINGS_FILE
    data = Path(DATA_DIR)
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        db = Path(tmp) / "acql.db"
        _db_copy(db)
        zf.write(db, "data/acql.db")
        for path in sorted(data.rglob("*")):
            rel = path.relative_to(data)
            if (not path.is_file() or path.name in SKIP_FILES or path.suffix.lower() in (".zip", ".exe")
                    or any(part in SKIP_DIRS for part in rel.parts) or path.name.endswith("preview.html")):
                continue
            zf.write(path, f"data/{rel.as_posix()}")
        for sheet in _sheets():
            if not sheet.is_file():
                continue
            try:
                sheet.resolve().relative_to(data.resolve())
                continue                       # already packed with data/
            except ValueError:
                pass
            inside = "root" if sheet.resolve().parent == Path(ROOT).resolve() else "data"
            zf.write(sheet, f"{inside}/{sheet.name}")
        if SETTINGS_FILE.is_file():
            try:
                kept = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                kept["data_dirs"] = []          # their sheets are packed into data/
                zf.writestr("root/acql-settings.json", json.dumps(kept, indent=2))
            except ValueError:
                pass
        zf.writestr("made.json", json.dumps({"at": time.time()}))
    return buffer.getvalue()


def unpack(plain: bytes, root: Path) -> dict:
    """Into a checkout of the code (the cloud): data/ and the root's sheets."""
    made = {}
    with zipfile.ZipFile(io.BytesIO(plain)) as zf:
        for name in zf.namelist():
            if name == "made.json":
                made = json.loads(zf.read(name))
                continue
            top, _, rest = name.partition("/")
            if top not in ("data", "root") or not rest or ".." in Path(rest).parts:
                continue
            target = (root / "data" / rest) if top == "data" else (root / rest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    return made


# ---- carrying the cloud's own record between runs ---------------------------
def export_carried(path: Path) -> None:
    from .. import store
    path.write_text(json.dumps({kind: store.items(kind) for kind in CARRIED}), encoding="utf-8")


def merge_carried(path: Path) -> int:
    """What earlier cloud runs sent, put back so nothing goes out twice."""
    from .. import store
    if not path.is_file():
        return 0
    kept = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for kind in CARRIED:
        here = store.items(kind)
        for key, value in (kept.get(kind) or {}).items():
            mine = here.get(key)
            newer = (isinstance(value, dict) and isinstance(mine, dict)
                     and float(value.get("at", 0) or 0) > float(mine.get("at", 0) or 0))
            if mine is None or newer:
                store.put(kind, key, value)
                added += 1
    return added


# ---- the upload (PC) and download (cloud) -----------------------------------
def _web():
    from .webpublish import WebSettings
    web = WebSettings.load()
    if not web.ready:
        raise SnapshotError("the pool website isn't set up, so there's nowhere to upload")
    return web


def _request(url: str, *, token: str = "", method: str = "GET", data: bytes | None = None,
             kind: str = "application/json") -> tuple[int, bytes]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ACQL-Dashboard",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = kind
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""
    except (urllib.error.URLError, OSError) as exc:
        raise SnapshotError(f"couldn't reach GitHub ({exc})") from exc


def _release(repo: str, token: str = "", *, create: bool = False) -> dict:
    status, body = _request(f"https://api.github.com/repos/{repo}/releases/tags/{TAG}", token=token)
    if status == 200:
        return json.loads(body)
    if status == 404 and create:
        status, body = _request(f"https://api.github.com/repos/{repo}/releases", token=token, method="POST",
                                data=json.dumps({"tag_name": TAG, "name": TAG, "body": "",
                                                 "prerelease": True}).encode())
        if status == 201:
            return json.loads(body)
    raise SnapshotError(f"GitHub said {status} while looking for the {TAG} release on {repo}"
                        + (" - the website token needs Contents: read and write" if status in (403, 404) else ""))


def upload(*, force: bool = False, now: float | None = None) -> bool:
    """Pack, lock and upload; then remove the older copies. False when not due."""
    now = time.time() if now is None else now
    values = _settings()
    if not values.get("sealed_key"):
        return False
    if not force and now - float(values.get("last_upload", 0) or 0) < EVERY:
        return False
    web = _web()
    repo, token = f"{web.user}/{web.repo}", web.token
    blob = lock(pack(), master_key())
    release = _release(repo, token, create=True)
    name = f"v-{int(now)}.bin"
    url = release["upload_url"].split("{")[0] + f"?name={name}"
    status, body = _request(url, token=token, method="POST", data=blob, kind="application/octet-stream")
    if status != 201:
        raise SnapshotError(f"GitHub said {status} to the upload")
    for asset in release.get("assets", []):
        if asset.get("name") != name:
            _request(asset["url"], token=token, method="DELETE")
    values["last_upload"] = now
    values["size"] = len(blob)
    _save(values)
    return True


def upload_quietly() -> None:
    """For headless.py: upload when due; a failure is logged, never fatal."""
    try:
        from ..ui.pages.base import write_log
        if upload():
            write_log(f"headless: snapshot uploaded for GitHub ({_settings().get('size', 0) // 1024} KB)")
    except Exception as exc:  # noqa: BLE001
        try:
            from ..ui.pages.base import write_log
            write_log(f"headless: snapshot not uploaded: {exc}")
        except Exception:  # noqa: BLE001
            pass


def download(repo: str, root: Path) -> dict:
    """The newest snapshot, unlocked into `root` (the cloud checkout)."""
    release = _release(repo, os.environ.get("GITHUB_TOKEN", ""))
    assets = sorted((a for a in release.get("assets", []) if a.get("name", "").startswith("v-")),
                    key=lambda a: a["name"], reverse=True)
    if not assets:
        raise SnapshotError("no snapshot uploaded yet")
    request = urllib.request.Request(assets[0]["browser_download_url"], headers={"User-Agent": "ACQL"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
        blob = reply.read()
    made = unpack(unlock(blob, master_key()), root)
    made["name"] = assets[0]["name"]
    return made


# ---- GitHub's hourly run ----------------------------------------------------
def due(now: float | None = None) -> list[str]:
    """Which of the PC's timed sends are due and not yet done today (local time,
    so GitHub's late starts and daylight saving don't matter)."""
    from .. import store
    now = time.time() if now is None else now
    local = time.localtime(now)
    today = time.strftime("%Y-%m-%d", local)
    return [job for job, (days, start, until) in JOBS.items()
            if local.tm_wday in days and start <= local.tm_hour < until
            and not store.get("cloudrun", f"{job}:{today}", None)]


def cloud_run(*, dry_run: bool = False, now: float | None = None) -> int:
    """Every hour on GitHub: the deadline texts, and the card or brief when due.
    Prints only what was done - the run's log is public."""
    from .. import headless, store
    now = time.time() if now is None else now
    if not cloud_sends() and not dry_run:
        print("Cloud sending is off (on the PC: python -m acql.site.snapshot --cloud-on). Nothing sent.")
        return 0
    import contextlib

    def quiet(args: list[str]) -> int:
        # the job's own lines (subjects, counts) go to the log file, not GitHub's public page
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return headless.main(args)

    flag = ["--dry-run"] if dry_run else []
    worst = quiet(["--alerts", *flag])
    print("deadline reminder: checked")
    jobs = due(now) if not dry_run else list(JOBS)
    for job in jobs:
        code = quiet([f"--{job}", *flag])
        print(f"{'card email' if job == 'email' else 'Sunday brief'}: "
              + ("ok" if code == 0 else "FAILED") + (" (dry run, nothing sent)" if dry_run else ""))
        if code == 0 and not dry_run:
            store.put("cloudrun", f"{job}:{time.strftime('%Y-%m-%d', time.localtime(now))}", now)
        worst = worst or code
    return worst


# ---- the command line -------------------------------------------------------
def _clip(text: str) -> bool:
    try:
        import subprocess
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acql.site.snapshot", description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--new-key", "--copy-key", "--upload", "--cloud-on", "--cloud-off", "--status"):
        group.add_argument(flag, action="store_true")
    group.add_argument("--fetch", metavar="OWNER/REPO", help="(GitHub's job) download and unlock")
    group.add_argument("--carry-in", metavar="FILE", help="(GitHub's job) merge what earlier runs sent")
    group.add_argument("--carry-out", metavar="FILE", help="(GitHub's job) keep what this run sent")
    group.add_argument("--run", action="store_true", help="(GitHub's job) send whatever is due")
    parser.add_argument("--dry-run", action="store_true", help="with --run: build everything, send nothing")
    args = parser.parse_args(argv)
    try:
        if args.run:
            return cloud_run(dry_run=args.dry_run)
        if args.fetch:
            from ..config import ROOT
            made = download(args.fetch, Path(ROOT))
            age = (time.time() - float(made.get("at", 0))) / 3600
            print(f"snapshot {made['name']} unpacked ({age:.1f} hours old)")
            if age > 72:
                print("::warning::the snapshot is more than three days old - is the PC uploading?")
            return 0
        if args.carry_in:
            print(f"{merge_carried(Path(args.carry_in))} earlier sends carried in")
            return 0
        if args.carry_out:
            export_carried(Path(args.carry_out))
            return 0
        values = _settings()
        if args.new_key:
            if values.get("sealed_key"):
                print("There's already a key. To replace it, delete it from GitHub's secrets first,"
                      " then run --cloud-off and ask for a new one.")
                return 1
            from .mailer import seal
            key = secrets.token_hex(32)
            values["sealed_key"] = seal(key)
            _save(values)
            print("Key made and kept on this PC."
                  + (" It's on the clipboard: paste it into GitHub as ACQL_SNAPSHOT_KEY." if _clip(key)
                     else " Run --copy-key to put it on the clipboard."))
            return 0
        if args.copy_key:
            print("Copied to the clipboard." if _clip(master_key().hex()) else "Couldn't reach the clipboard.")
            return 0
        if args.upload:
            upload(force=True)
            print(f"Uploaded ({_settings().get('size', 0) // 1024} KB).")
            return 0
        if args.cloud_on or args.cloud_off:
            values["sending"] = bool(args.cloud_on)
            _save(values)
            if args.cloud_on:
                upload(force=True)        # GitHub has to see the switch too
            print("GitHub sends the card, the Sunday brief and the deadline texts now; this PC won't."
                  if args.cloud_on else "This PC sends again.")
            return 0
        last = float(values.get("last_upload", 0) or 0)
        print(f"key: {'set' if values.get('sealed_key') else 'not made'}; "
              f"sending: {'GitHub' if values.get('sending') else 'this PC'}; last upload: "
              + (time.strftime("%a %d %b %I:%M %p", time.localtime(last)) if last else "never"))
        return 0
    except SnapshotError as exc:
        print(f"Snapshot: {exc}")
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
