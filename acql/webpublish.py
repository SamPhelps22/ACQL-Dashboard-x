"""Put the pool page on the pool's own website: a free GitHub Pages site.

Anyone opens https://<user>.github.io/<repo>/ with no account and no sign-in.
The dashboard uploads the page as index.html in that repository through
GitHub's API, turning Pages on the first time. What it needs, once: the
GitHub user name, the repository, and a token that may write that one
repository's contents and Pages settings. The token is kept sealed to this
Windows account, like the Gmail app password.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from .mailer import seal, unseal

API = "https://api.github.com"
TIMEOUT = 25
TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new"
NEW_REPO_PAGE = "https://github.com/new"


class WebPublishError(Exception):
    """Something the person can act on, in plain English."""


@dataclass
class WebSettings:
    user: str = ""
    repo: str = "acql-pool"
    sealed_token: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.user and self.repo and self.sealed_token)

    @property
    def token(self) -> str:
        return unseal(self.sealed_token)

    def set_token(self, token: str) -> None:
        self.sealed_token = seal(token.strip())

    @property
    def url(self) -> str:
        return site_url(self.user, self.repo)

    @classmethod
    def load(cls) -> WebSettings:
        from . import store
        raw = store.get("settings", "web", {})
        if not isinstance(raw, dict):
            return cls()
        return cls(
            user=str(raw.get("user", "")).strip(),
            repo=str(raw.get("repo", "acql-pool")).strip() or "acql-pool",
            sealed_token=str(raw.get("sealed_token", "")),
        )

    def save(self) -> None:
        from . import store
        store.put("settings", "web", asdict(self))


def site_url(user: str, repo: str) -> str:
    user = user.strip().lower()
    if repo.strip().lower() == f"{user}.github.io":
        return f"https://{user}.github.io/"
    return f"https://{user}.github.io/{repo.strip()}/"


def _call(settings: WebSettings, method: str, path: str, body: dict | None = None,
          *, opener=None) -> tuple[int, dict]:
    """(status, json) for one API call; network trouble raises WebPublishError."""
    request = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ACQL-Dashboard",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    open_ = opener or (lambda req: urllib.request.urlopen(req, timeout=TIMEOUT))
    try:
        with open_(request) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}")
        except ValueError:
            detail = {}
        return exc.code, detail if isinstance(detail, dict) else {}
    except (urllib.error.URLError, OSError) as exc:
        raise WebPublishError(f"Couldn't reach GitHub ({exc}). Check the connection and try again.") from exc


def _explain(status: int, settings: WebSettings, doing: str) -> WebPublishError:
    where = f"{settings.user}/{settings.repo}"
    if status == 401:
        return WebPublishError("GitHub didn't accept the token - it may be mistyped or expired. "
                               "Make a new one and enter it under the pool page's web settings.")
    if status == 404:
        return WebPublishError(f"GitHub can't find the repository {where}, or the token isn't allowed "
                               "to see it. Check the name, and that the token was made for that repository.")
    if status == 403 and doing == "turn on Pages":
        return WebPublishError(f"The page is uploaded; the website just needs switching on, once. On GitHub "
                               f"open {where} > Settings > Pages, set Source to 'Deploy from a branch', "
                               "Branch 'main' and '/ (root)', and Save. Then publish again.")
    if status == 403:
        return WebPublishError(f"The token isn't allowed to {doing} in {where}. Give it Contents and "
                               "Pages permission (read and write) for that repository.")
    if status == 422 and doing == "turn on Pages":
        return WebPublishError(f"GitHub wouldn't turn on Pages for {where}. Make sure the repository "
                               "is Public, then try again.")
    return WebPublishError(f"GitHub said no while trying to {doing} ({status}). Try again in a minute.")


def publish(settings: WebSettings, page: str, *, message: str = "Update the pool page",
            files: dict[str, bytes] | None = None, opener=None) -> str:
    """Upload `page` as index.html (and any `files` beside it), and make sure
    Pages serves it. "__SITE__" in the page becomes the site's own address.
    Returns the site's link."""
    if not settings.ready:
        raise WebPublishError("The pool's website isn't set up yet.")
    repo = f"/repos/{settings.user}/{settings.repo}"
    status, info = _call(settings, "GET", repo, opener=opener)
    if status != 200:
        raise _explain(status, settings, "read the repository")
    branch = info.get("default_branch") or "main"
    # GitHub's own spelling of the names: a repository renamed since setup
    # (acql---pool -> ACQL---Pool) still answers to the old one, but the
    # website's link follows the real name. Settings are brought up to date.
    real_repo = info.get("name") or settings.repo
    real_user = (info.get("owner") or {}).get("login") or settings.user
    link = site_url(real_user, real_repo)

    pages_status, pages = _call(settings, "GET", f"{repo}/pages", opener=opener)
    if pages_status == 200 and str(pages.get("html_url", "")).startswith("https://"):
        link = pages["html_url"]
    link = link if link.endswith("/") else link + "/"

    # the picture first, so the page never points at one that isn't there yet
    uploads = dict(files or {})
    uploads["index.html"] = page.replace("__SITE__", link).encode("utf-8")
    for name, content in uploads.items():
        status, current = _call(settings, "GET", f"{repo}/contents/{name}?ref={branch}", opener=opener)
        sha = current.get("sha") if status == 200 else None
        body = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": branch,
            **({"sha": sha} if sha else {}),
        }
        status, _ = _call(settings, "PUT", f"{repo}/contents/{name}", body, opener=opener)
        if status not in (200, 201):
            raise _explain(status, settings, "write the page")

    if pages_status == 404:
        status, _ = _call(settings, "POST", f"{repo}/pages",
                          {"source": {"branch": branch, "path": "/"}}, opener=opener)
        if status not in (201, 409):          # 409: it was switched on meanwhile
            raise _explain(status, settings, "turn on Pages")
    elif pages_status != 200:
        raise _explain(pages_status, settings, "check Pages")
    if (real_user, real_repo) != (settings.user, settings.repo):
        settings.user, settings.repo = real_user, real_repo
        try:
            settings.save()
        except Exception:  # noqa: BLE001 - the link is right either way
            pass
    return link
