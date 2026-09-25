"""Everything the app remembers, in one file: acql.db in the data folder.

Before this, six JSON files did the job - predictions, typed spreads and pick
sheets beside run.py, odds, saved cards and email settings in the data folder.
Each was rewritten whole on every save, so a crash or a OneDrive sync at the
wrong moment could leave one half-written, and backing the app's memory up
meant finding six files in two places.

Now it is one SQLite database (part of Python - nothing to install):

  * every save is a transaction: it lands completely or not at all;
  * a copy is kept each day in data/backups/, the last fourteen of them;
  * the old JSON files are read in once, the first time the new version
    runs, and then left exactly where they were - an older copy of the app
    still finds them if it is ever put back.

The shape is deliberately simple - documents, grouped by kind:

    kind         key           value
    forecasts    "3"           week 3's predictions file, as it was stored
    picks        "3"           week 3's pick sheet
    spreads      "3"           spreads typed in for week 3
    odds         "weeks"       fetched lines, by week
    cards        "weeks"       saved and model cards, by week
    settings     "email"       where the recap is emailed from and to

so each module keeps working with the same dictionaries it always had, and
only where they are kept has changed.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

DB_NAME = "acql.db"
BACKUP_FOLDER = "backups"
KEEP_BACKUPS = 14
#: How long a write waits for the file if something else has it (OneDrive
#: uploading it, usually) before giving up.
BUSY_TIMEOUT_S = 10

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None
_PATH: Path | None = None
_OVERRIDE: Path | None = None
#: Bumped on every write from this process; with SQLite's own data_version
#: (which moves when another process writes) it says when a cache is stale.
_WRITES = 0
_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}


class StoreError(Exception):
    """The database could not be read or written, in words fit to show."""


# ---- where it lives -----------------------------------------------------------
def data_dir() -> Path:
    try:
        from .config import DATA_DIR  # lazy: config never imports this
        return Path(DATA_DIR)
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent.parent / "data"


def project_root() -> Path:
    try:
        from .config import ROOT
        return Path(ROOT)
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return _OVERRIDE if _OVERRIDE is not None else data_dir() / DB_NAME


def use(path: str | Path | None) -> None:
    """Point the store at another file (tests), or back at the real one (None)."""
    global _OVERRIDE
    with _LOCK:
        close()
        _OVERRIDE = Path(path) if path is not None else None


def close() -> None:
    global _CONN, _PATH
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except sqlite3.Error:
                pass
        _CONN, _PATH = None, None
        _CACHE.clear()


# ---- the connection -------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    global _CONN, _PATH
    path = db_path()
    if _CONN is not None and _PATH == path:
        return _CONN
    close()
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    try:
        conn = sqlite3.connect(
            str(path), timeout=BUSY_TIMEOUT_S, isolation_level=None,
            check_same_thread=False,
        )
        # A plain rollback journal, not WAL: WAL keeps two extra files beside
        # the database, and a synced folder (OneDrive) copying those around on
        # their own is a known way to lose data. The journal only exists for
        # the instant of a write.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS docs ("
            " kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            " updated REAL NOT NULL, PRIMARY KEY (kind, key))"
        )
    except sqlite3.Error as exc:
        raise StoreError(f"Couldn't open {path}: {exc}") from exc
    _CONN, _PATH = conn, path
    _migrate(conn)
    if not fresh:
        _daily_backup(conn, path)
    return conn


def _version(conn: sqlite3.Connection) -> tuple[int, int]:
    try:
        outside = conn.execute("PRAGMA data_version").fetchone()[0]
    except sqlite3.Error:
        outside = -1
    return (outside, _WRITES)


def _write(statements: list[tuple[str, tuple]]) -> None:
    """Run writes as one transaction: all of them land, or none do."""
    global _WRITES
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for sql, args in statements:
                conn.execute(sql, args)
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise StoreError(f"Couldn't save to {db_path().name}: {exc}") from exc
        finally:
            _WRITES += 1
            _CACHE.clear()


# ---- documents ----------------------------------------------------------------------
def items(kind: str) -> dict:
    """Every document of one kind, as {key: value}. Cached until something writes."""
    with _LOCK:
        conn = _connect()
        version = _version(conn)
        cached = _CACHE.get(kind)
        if cached is not None and cached[0] == version:
            return cached[1]
        out = {}
        for key, value in conn.execute("SELECT key, value FROM docs WHERE kind = ?", (kind,)):
            try:
                out[key] = json.loads(value)
            except ValueError:
                continue
        _CACHE[kind] = (version, out)
        return out


def get(kind: str, key: str, default=None):
    found = items(kind).get(str(key))
    return default if found is None else found


def put(kind: str, key: str, value) -> None:
    _write([(
        "INSERT OR REPLACE INTO docs (kind, key, value, updated) VALUES (?, ?, ?, ?)",
        (kind, str(key), json.dumps(value), time.time()),
    )])


def delete(kind: str, key: str | None = None) -> None:
    """Remove one document, or every document of a kind."""
    if key is None:
        _write([("DELETE FROM docs WHERE kind = ?", (kind,))])
    else:
        _write([("DELETE FROM docs WHERE kind = ? AND key = ?", (kind, str(key)))])


def replace(kind: str, mapping: dict) -> None:
    """Make a kind exactly this mapping, in one transaction."""
    now = time.time()
    statements: list[tuple[str, tuple]] = [("DELETE FROM docs WHERE kind = ?", (kind,))]
    for key, value in mapping.items():
        statements.append((
            "INSERT INTO docs (kind, key, value, updated) VALUES (?, ?, ?, ?)",
            (kind, str(key), json.dumps(value), now),
        ))
    _write(statements)


def stamp(kind: str | None = None) -> tuple:
    """Changes whenever anything (or anything of `kind`) may have changed."""
    with _LOCK:
        conn = _connect()
        if kind is None:
            return _version(conn)
        row = conn.execute(
            "SELECT COUNT(*), MAX(updated) FROM docs WHERE kind = ?", (kind,)
        ).fetchone()
        return (kind, row[0], row[1])


def kinds() -> dict[str, int]:
    """How many documents of each kind - for the Data page and diagnostics."""
    with _LOCK:
        conn = _connect()
        return dict(conn.execute("SELECT kind, COUNT(*) FROM docs GROUP BY kind"))


# ---- reading the old JSON files in, once -------------------------------------------------
#: (kind, file name, folder) - "root" is beside run.py, "data" the data folder.
LEGACY = (
    ("forecasts", "acql-forecasts.json", "root"),
    ("spreads", "acql-spreads.json", "root"),
    ("picks", "acql-picks.json", "root"),
    ("odds", "acql-odds.json", "data"),
    ("cards", "acql-cards.json", "data"),
    ("settings/email", "acql-email.json", "data"),
)


def _legacy_path(name: str, where: str) -> Path:
    return (project_root() if where == "root" else data_dir()) / name


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring each old JSON file in the first time - and again only if it changes.

    Once a file is in, it is left alone: a kind emptied on purpose here (pick
    sheets cleared from the Data page, say) must not come back from the old
    file on the next start. The one exception is a file that has changed
    since it was read, which only an older copy of the app writes - after
    "Undo last update", used for a while, then the update installed again.
    Its documents are read in over the top; nothing else is removed.

    A file that can't be opened right now (OneDrive fetching it, a virus
    scanner holding it) is simply tried again next time.
    """
    global _WRITES
    done = {}
    for key, value in conn.execute("SELECT key, value FROM docs WHERE kind = 'meta'"):
        try:
            done[key] = json.loads(value)
        except ValueError:
            done[key] = {}
    for kind, name, where in LEGACY:
        marker = f"migrated:{name}"
        path = _legacy_path(name, where)
        try:
            info = path.stat() if path.is_file() else None
        except OSError:
            continue
        previous = done.get(marker)
        if previous is not None:
            if info is None:
                continue
            if (previous.get("mtime") == info.st_mtime and previous.get("size") == info.st_size):
                continue
        record = {"at": time.time(), "found": info is not None, "documents": 0}
        statements: list[tuple[str, tuple]] = []
        if info is not None:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue                          # try again on the next start
            try:
                raw = json.loads(text)
            except ValueError:
                raw = None
            record["mtime"], record["size"] = info.st_mtime, info.st_size
            if isinstance(raw, dict):
                now = time.time()
                if "/" in kind:                   # one file, one document
                    real, key = kind.split("/", 1)
                    statements.append((
                        "INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?)",
                        (real, key, json.dumps(raw), now),
                    ))
                    record["documents"] = 1
                else:
                    for key, value in raw.items():
                        statements.append((
                            "INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?)",
                            (kind, str(key), json.dumps(value), now),
                        ))
                    record["documents"] = len(raw)
            else:
                record["unreadable"] = True
        statements.append((
            "INSERT OR REPLACE INTO docs VALUES ('meta', ?, ?, ?)",
            (marker, json.dumps(record), time.time()),
        ))
        try:
            conn.execute("BEGIN IMMEDIATE")
            for sql, args in statements:
                conn.execute(sql, args)
            conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        _WRITES += 1
    _CACHE.clear()


def migrated() -> dict[str, dict]:
    """What was brought in from the old files, for the Data page."""
    return {
        key.split(":", 1)[1]: value
        for key, value in items("meta").items() if key.startswith("migrated:")
    }


# ---- backups ---------------------------------------------------------------------------
def backup_folder() -> Path:
    return db_path().parent / BACKUP_FOLDER


def _daily_backup(conn: sqlite3.Connection, path: Path) -> None:
    """One copy a day, the first time the app opens the store that day."""
    folder = path.parent / BACKUP_FOLDER
    target = folder / f"acql-{time.strftime('%Y-%m-%d')}.db"
    try:
        if not target.exists():
            folder.mkdir(parents=True, exist_ok=True)
            dest = sqlite3.connect(str(target))
            try:
                conn.backup(dest)
            finally:
                dest.close()
        # Dated names sort by date, so the oldest are first.
        old = sorted(folder.glob("acql-????-??-??.db"))
        for stale in old[:-KEEP_BACKUPS]:
            stale.unlink(missing_ok=True)
    except (OSError, sqlite3.Error):
        pass          # a backup is never worth failing a start over


def backup_now(target: str | Path) -> Path:
    """A copy of the whole store at `target` (Data page's "Back up now")."""
    with _LOCK:
        conn = _connect()
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(target))
        try:
            conn.backup(dest)
        finally:
            dest.close()
        return target


def restore_from(source: str | Path) -> None:
    """Replace the store with a backup. The current one is kept beside it first."""
    source = Path(source)
    if not source.is_file():
        raise StoreError(f"{source} isn't there.")
    with _LOCK:
        path = db_path()
        close()
        if path.exists():
            keep = path.with_name(f"acql-before-restore-{time.strftime('%Y%m%d-%H%M%S')}.db")
            shutil.copy2(path, keep)
        shutil.copy2(source, path)
        _connect()
