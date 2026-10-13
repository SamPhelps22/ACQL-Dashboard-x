"""The card on the phone, for one person: a locked page on the pool's website.

The pool's website is public, and so is the repository behind it. The card
must not be. So the card is encrypted on this computer, with a passphrase
only its owner knows, before anything is uploaded; what goes up is a page
holding scrambled text and a box to type the passphrase in. The phone's
browser does the unlocking. Without the passphrase the page is noise - to a
visitor, to GitHub, to anyone reading the repository.

    the lock        AES-256-GCM, the key stretched from the passphrase with
                    PBKDF2-HMAC-SHA256 (600,000 rounds, a fresh salt every
                    time). The browser's own WebCrypto opens it; a wrong
                    passphrase, or one changed byte, opens nothing.
    the passphrase  kept sealed to this Windows account, like the website's
                    token. It is the whole lock: a short one can be guessed
                    by trying, so a short one is refused.
    the page        says nothing about what it holds - no name, no week.
                    Nothing on the website links to it by name.

The standard library has no AES, so the cipher is written out here, small
and slow (a card is a few kilobytes) and checked against the standard's own
test vectors in the tests. Nothing here knows about Qt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass

from .mailer import seal, unseal

#: The file on the website. Nothing links to it by name.
FILE = "locker.html"
ROUNDS = 600_000
#: Shorter than this can be guessed by trying.
SHORTEST = 14


class LockedPageError(Exception):
    """Something the person can act on, in plain English."""


# ---- AES-256-GCM (NIST SP 800-38D), enough of it to lock a page ---------------------------------
def _tables() -> tuple[list[int], list[int]]:
    box, p, q = [0] * 256, 1, 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        box[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    box[0] = 0x63
    twice = [((v << 1) ^ 0x1B) & 0xFF if v & 0x80 else v << 1 for v in range(256)]
    return box, twice


_SBOX, _TWICE = _tables()


def _expand(key: bytes) -> list[list[int]]:
    words = [list(key[i:i + 4]) for i in range(0, len(key), 4)]
    n, rounds, rcon = len(words), len(key) // 4 + 6, 1
    for i in range(n, 4 * (rounds + 1)):
        word = list(words[i - 1])
        if i % n == 0:
            word = [_SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _TWICE[rcon]
        elif n > 6 and i % n == 4:
            word = [_SBOX[b] for b in word]
        words.append([a ^ b for a, b in zip(words[i - n], word)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(rounds + 1)]


def _block(keys: list[list[int]], block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, keys[0])]
    for r in range(1, len(keys)):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]              # each row moved along
        if r < len(keys) - 1:
            mixed = []
            for c in range(0, 16, 4):
                a = s[c:c + 4]
                every = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ every ^ _TWICE[a[i] ^ a[(i + 1) % 4]] for i in range(4)]
            s = mixed
        s = [b ^ k for b, k in zip(s, keys[r])]
    return bytes(s)


def _times(x: int, y: int) -> int:
    z = 0
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= y
        y = (y >> 1) ^ (0xE1 << 120) if y & 1 else y >> 1
    return z


def encrypt(key: bytes, iv: bytes, plain: bytes, also: bytes = b"") -> bytes:
    """AES-GCM: the scrambled text with its 16-byte tag on the end, as WebCrypto wants it."""
    if len(key) not in (16, 24, 32) or len(iv) != 12:
        raise ValueError("a 128/192/256-bit key and a 96-bit iv")
    keys = _expand(key)
    h = int.from_bytes(_block(keys, bytes(16)), "big")
    first = iv + b"\x00\x00\x00\x01"
    out = bytearray()
    for n, i in enumerate(range(0, len(plain), 16), start=2):
        pad = _block(keys, iv + n.to_bytes(4, "big"))
        out += bytes(a ^ b for a, b in zip(plain[i:i + 16], pad))
    tag = 0
    for part in (also, bytes(out)):
        for i in range(0, len(part), 16):
            tag = _times(tag ^ int.from_bytes(part[i:i + 16].ljust(16, b"\0"), "big"), h)
    tag = _times(tag ^ ((len(also) * 8) << 64 | len(out) * 8), h)
    tag ^= int.from_bytes(_block(keys, first), "big")
    return bytes(out) + tag.to_bytes(16, "big")


# ---- locking ------------------------------------------------------------------------------------
def lock(plain: bytes, passphrase: str, *, salt: bytes | None = None, iv: bytes | None = None,
         rounds: int = ROUNDS) -> dict:
    """`plain` locked with `passphrase`, as the plain data the page carries."""
    salt = os.urandom(16) if salt is None else salt
    iv = os.urandom(12) if iv is None else iv
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, rounds, dklen=32)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return {"v": 1, "rounds": rounds, "salt": b64(salt), "iv": b64(iv), "data": b64(encrypt(key, iv, plain))}


def weak(passphrase: str) -> str:
    """Why this passphrase won't do, or "" when it will."""
    text = passphrase.strip()
    if len(text) < SHORTEST:
        return (f"Make it at least {SHORTEST} characters - four or five unrelated words is easy to type on a "
                "phone and hard to guess. The page is public; the passphrase is the only lock.")
    if len(set(text.casefold())) < 6:
        return "Too repetitive to be a lock - use four or five unrelated words."
    return ""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow, noarchive">
<meta name="referrer" content="no-referrer">
<title>&middot;</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #07090d; color: #e9e6dc;
  font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width: 720px; margin: 0 auto; padding: 22px 16px calc(28px + env(safe-area-inset-bottom, 0px)); }
form { max-width: 380px; margin: 22vh auto 0; display: grid; gap: 12px; }
input[type=password] { width: 100%; padding: 13px 14px; font: inherit; color: inherit; background: #10141c;
  border: 1px solid #2a3140; border-radius: 10px; outline: none; }
input[type=password]:focus { border-color: #d7b44a; }
button { padding: 13px 14px; font: 600 16px/1 inherit; color: #07090d; background: #d7b44a; border: 0;
  border-radius: 10px; cursor: pointer; }
button[disabled] { opacity: .55; }
label { display: flex; gap: 8px; align-items: center; color: #8d95a5; font-size: 14px; }
#say { min-height: 1.4em; color: #e0796b; font-size: 14px; }
#card { display: none; }
#card .sheet { background: #fff; color: #111827; border-radius: 14px; padding: 6px 14px 14px; overflow-x: auto; }
#bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 2px 12px;
  color: #8d95a5; font-size: 13px; }
#bar a { color: #6fa8ff; text-decoration: none; }
</style></head><body><main>
<form id="door" autocomplete="off">
  <input id="pass" type="password" placeholder="Passphrase" autocomplete="current-password" autofocus>
  <label><input id="keep" type="checkbox"> Remember on this device</label>
  <button id="go" type="submit">Open</button>
  <div id="say" role="status"></div>
</form>
<section id="card"><div id="bar"><span id="when"></span><a href="#" id="shut">Lock</a></div>
<div class="sheet" id="sheet"></div></section>
</main>
<script>
(function () {
  "use strict";
  var BOX = __BOX__;
  var KEPT = "locker-pass";
  var door = document.getElementById("door"), pass = document.getElementById("pass"),
      keep = document.getElementById("keep"), go = document.getElementById("go"),
      say = document.getElementById("say"), card = document.getElementById("card");
  function bytes(text) {
    var raw = atob(text), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function open(phrase) {
    var subtle = window.crypto && window.crypto.subtle;
    if (!subtle) return Promise.reject(new Error("old"));
    return subtle.importKey("raw", new TextEncoder().encode(phrase), "PBKDF2", false, ["deriveKey"])
      .then(function (base) {
        return subtle.deriveKey({ name: "PBKDF2", salt: bytes(BOX.salt), iterations: BOX.rounds, hash: "SHA-256" },
          base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
      })
      .then(function (key) { return subtle.decrypt({ name: "AES-GCM", iv: bytes(BOX.iv) }, key, bytes(BOX.data)); })
      .then(function (plain) { return JSON.parse(new TextDecoder().decode(plain)); });
  }
  function show(inside) {
    document.getElementById("sheet").innerHTML = inside.html;
    var made = new Date(inside.made * 1000);
    document.getElementById("when").textContent = "As of " + made.toLocaleString("en-US",
      { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    door.style.display = "none";
    card.style.display = "block";
    document.documentElement.setAttribute("data-open", "1");
  }
  function attempt(phrase, quiet) {
    go.disabled = true;
    say.textContent = quiet ? "" : "Opening\\u2026";
    return open(phrase).then(function (inside) {
      try { if (keep.checked) localStorage.setItem(KEPT, phrase); } catch (e) { /* private mode */ }
      show(inside);
    }).catch(function (err) {
      go.disabled = false;
      if (quiet) { try { localStorage.removeItem(KEPT); } catch (e) { /* nothing kept */ } say.textContent = ""; return; }
      say.textContent = err && err.message === "old" ? "This browser is too old to open it." : "That didn\\u2019t open it.";
    });
  }
  door.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pass.value) attempt(pass.value, false);
  });
  document.getElementById("shut").addEventListener("click", function (event) {
    event.preventDefault();
    try { localStorage.removeItem(KEPT); } catch (e) { /* nothing kept */ }
    location.reload();
  });
  var kept = null;
  try { kept = localStorage.getItem(KEPT); } catch (e) { /* private mode */ }
  if (kept) { keep.checked = true; attempt(kept, true); }
})();
</script></body></html>
"""


def page(inside_html: str, passphrase: str, *, made: float | None = None, **fixed) -> str:
    """The whole locked page: `inside_html` scrambled, and the door to it."""
    inside = json.dumps({"html": inside_html, "made": time.time() if made is None else made})
    return PAGE.replace("__BOX__", json.dumps(lock(inside.encode("utf-8"), passphrase, **fixed)))


# ---- settings -----------------------------------------------------------------------------------
@dataclass
class LockedSettings:
    sealed_passphrase: str = ""
    on: bool = True
    shown: str = ""             # the fingerprint of the card last uploaded
    shown_at: float = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.on and self.sealed_passphrase)

    def set_passphrase(self, passphrase: str) -> None:
        self.sealed_passphrase = seal(passphrase.strip()) if passphrase.strip() else ""
        self.shown = ""                         # a new lock: what is up there no longer opens with it

    @classmethod
    def load(cls) -> LockedSettings:
        from .. import store
        raw = store.get("settings", "locked-page", {})
        if not isinstance(raw, dict):
            return cls()
        return cls(sealed_passphrase=str(raw.get("sealed_passphrase", "")), on=bool(raw.get("on", True)),
                   shown=str(raw.get("shown", "")), shown_at=float(raw.get("shown_at", 0.0) or 0.0))

    def save(self) -> None:
        from .. import store
        store.put("settings", "locked-page", asdict(self))


def address(site: str) -> str:
    return (site if site.endswith("/") else site + "/") + FILE


def put(inside_html: str, *, now: float | None = None, opener=None) -> str | None:
    """Lock `inside_html` and upload it, when a passphrase is set and the
    card has changed since the last upload. Returns the page's address, or
    None when there was nothing to do."""
    from . import webpublish
    settings = LockedSettings.load()
    web = webpublish.WebSettings.load()
    if not settings.ready or not web.ready:
        return None
    mark = hashlib.sha256((settings.sealed_passphrase + "\0" + inside_html).encode("utf-8")).hexdigest()
    if mark == settings.shown:
        return None
    try:
        passphrase = unseal(settings.sealed_passphrase)
    except Exception as exc:  # noqa: BLE001 - sealed on another Windows account
        raise LockedPageError("The private page's passphrase can't be read on this account - set it again.") from exc
    body = page(inside_html, passphrase, made=now).encode("utf-8")
    try:
        link = webpublish.put_file(web, FILE, body, message="Update", opener=opener)
    except webpublish.WebPublishError as exc:
        raise LockedPageError(str(exc)) from exc
    settings.shown, settings.shown_at = mark, time.time() if now is None else now
    settings.save()
    return address(link)


def card_now(season, now: float | None = None) -> str | None:
    """The card for the week ahead as it stands on what is stored - nothing
    is fetched. None when no week is open to pick or nothing is priced."""
    from ..feeds import oddslock, results
    from . import cardmail
    now = time.time() if now is None else now
    year = results.season_year(season)
    week = next((w for w in results.calendar_weeks(year, now) if oddslock.lock_time(year, w) > now), None)
    if week is None or season.weeks.get(week) is None:
        return None
    card = cardmail.compose(season, week, now=now)
    return card.html if card is not None else None


def refresh(season, *, now: float | None = None, opener=None) -> str | None:
    """Bring the page up to date with the card as it stands. None when there was nothing to do."""
    if not LockedSettings.load().ready:
        return None
    inside = card_now(season, now)
    return put(inside, now=now, opener=opener) if inside else None


def take_down(*, opener=None) -> bool:
    """Remove the page from the website. True when one was there."""
    from . import webpublish
    web = webpublish.WebSettings.load()
    if not web.ready:
        return False
    try:
        gone = webpublish.remove_file(web, FILE, message="Update", opener=opener)
    except webpublish.WebPublishError as exc:
        raise LockedPageError(str(exc)) from exc
    settings = LockedSettings.load()
    settings.shown, settings.shown_at = "", 0.0
    settings.save()
    return gone
