"""Updates from the project's GitHub repository, found by themselves.

Each release puts two files in the repository's updates/ folder:
latest.json (the version, the zip's name, its SHA-256, the notes) and the
update zip itself. The dashboard asks for latest.json every so often; when
it names a newer version it downloads the zip, checks it is exactly the file
the release made, and hands it to the installer the "Install update" button
uses - the current code is backed up first and put back if the new version
won't start.

It is asked with a token: the website's own (any token can read a public
repository; a private one needs it given access), or one just for updates.
Nothing here knows about Qt.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

API = "https://api.github.com"
TIMEOUT = 30
FOLDER = "updates"
MANIFEST = "latest.json"
#: Where the project lives: github.com/<the website's user>/ACQL-Dashboard-x.
DEFAULT_REPO = "ACQL-Dashboard-x"
#: How often it looks by itself.
EVERY_S = 12 * 3600


class UpdateCheckError(Exception):
    """Something the person can act on, in plain English."""


class NothingPublished(UpdateCheckError):
    """The repository has no list of updates yet: no release has been made. Not a fault."""


@dataclass
class UpdateSettings:
    owner: str = ""             # blank: the website's GitHub user
    repo: str = DEFAULT_REPO
    sealed_token: str = ""      # blank: the website's token
    automatic: bool = True

    @classmethod
    def load(cls) -> UpdateSettings:
        from . import store
        raw = store.get("settings", "updates", {})
        if not isinstance(raw, dict):
            return cls()
        return cls(owner=str(raw.get("owner", "")).strip(),
                   repo=str(raw.get("repo", DEFAULT_REPO)).strip() or DEFAULT_REPO,
                   sealed_token=str(raw.get("sealed_token", "")),
                   automatic=bool(raw.get("automatic", True)))

    def save(self) -> None:
        from . import store
        store.put("settings", "updates", asdict(self))

    def set_token(self, token: str) -> None:
        from .mailer import seal
        self.sealed_token = seal(token.strip()) if token.strip() else ""

    def resolved(self) -> tuple[str, str, str]:
        """(owner, repo, token), the website's filling the gaps."""
        from .mailer import unseal
        owner, token = self.owner, unseal(self.sealed_token) if self.sealed_token else ""
        if not owner or not token:
            try:
                from .webpublish import WebSettings
                web = WebSettings.load()
                owner = owner or web.user
                token = token or (web.token if web.sealed_token else "")
            except Exception:  # noqa: BLE001 - no website set up: nothing to borrow
                pass
        return owner, self.repo, token

    @property
    def ready(self) -> bool:
        owner, repo, token = self.resolved()
        return bool(owner and repo and token)


@dataclass(frozen=True)
class Available:
    version: str
    file: str
    sha256: str
    size: int
    notes: str


def version_tuple(text: str) -> tuple[int, ...]:
    from .updater import version_tuple as vt
    return vt(text)


def _get(settings: UpdateSettings, path: str, *, opener=None) -> bytes:
    owner, repo, token = settings.resolved()
    if not (owner and repo and token):
        raise UpdateCheckError("Updates from GitHub aren't set up: the repository and a token "
                               "are needed (Data & Update > Updates from GitHub).")
    url = f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/contents/{path}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ACQL-Dashboard",
    })
    open_ = opener or (lambda req: urllib.request.urlopen(req, timeout=TIMEOUT))
    try:
        with open_(request) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        where = f"{owner}/{repo}"
        if exc.code == 401:
            raise UpdateCheckError("GitHub didn't accept the token for updates - it may have expired. "
                                   "Make a new one and enter it under Updates from GitHub.") from exc
        if exc.code == 404:
            raise (NothingPublished if path.endswith(MANIFEST) else UpdateCheckError)(
                f"Nothing to update from in {where} yet: it has no {path}. A release puts it "
                "there. (If the repository is private, the token also needs read access to "
                "its Contents.)"
            ) from exc
        if exc.code == 403:
            raise UpdateCheckError(
                f"GitHub won't show {where} to this token. Give the token read access to that "
                "repository's Contents (or enter one that has it under Updates from GitHub)."
            ) from exc
        raise UpdateCheckError(f"GitHub said no while looking for updates ({exc.code}). "
                               "It'll try again later.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateCheckError(f"Couldn't reach GitHub to look for updates ({exc}).") from exc


def latest(settings: UpdateSettings, *, opener=None) -> Available:
    """What the repository's updates/latest.json says is the newest version."""
    raw = _get(settings, f"{FOLDER}/{MANIFEST}", opener=opener)
    try:
        data = json.loads(raw.decode("utf-8"))
        found = Available(version=str(data["version"]), file=str(data["file"]),
                          sha256=str(data["sha256"]).lower(), size=int(data.get("size", 0)),
                          notes=str(data.get("notes", "")))
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateCheckError("The repository's list of updates couldn't be read.") from exc
    if "/" in found.file or "\\" in found.file or not found.file.endswith(".zip"):
        raise UpdateCheckError("The repository's list of updates names an odd file; not downloaded.")
    return found


def newer(found: Available, current: str) -> bool:
    return version_tuple(found.version) > version_tuple(current)


def download(settings: UpdateSettings, found: Available, folder: Path, *, opener=None) -> Path:
    """The update zip, saved in `folder` - only if it is exactly the file the release made."""
    data = _get(settings, f"{FOLDER}/{urllib.parse.quote(found.file)}", opener=opener)
    if hashlib.sha256(data).hexdigest() != found.sha256:
        raise UpdateCheckError(f"The download of {found.version} didn't match the release - "
                               "nothing was installed. It'll try again later.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / found.file
    part = target.with_suffix(".part")
    part.write_bytes(data)
    part.replace(target)
    return target


# ---- when to look ---------------------------------------------------------------------
def last_checked() -> float | None:
    from . import store
    at = store.get("settings", "updates-checked", None)
    return float(at) if isinstance(at, (int, float)) else None


def note_checked(at: float | None = None) -> None:
    from . import store
    store.put("settings", "updates-checked", time.time() if at is None else at)


def due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    last = last_checked()
    return last is None or now - last >= EVERY_S


# ---- the publishing side (release/publish.py) -------------------------------------------
def manifest_for(zip_path: Path, version: str, notes: str = "") -> dict:
    data = Path(zip_path).read_bytes()
    return {"version": version, "file": Path(zip_path).name, "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data), "notes": notes}
