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
<meta name="theme-color" content="#05070b">
<title>&middot;</title>
<style>
:root { color-scheme: dark; --bg: #05070b; --panel: #0b0f17; --line: #1c2433; --ink: #ece8dc; --dim: #7f889a;
  --gold: #d7b44a; --blue: #4aa8ff; --bad: #ff6b5b; --mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace; }
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { min-height: 100vh; background: var(--bg); color: var(--ink); overflow-x: hidden;
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
body::before { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(60vmax 40vmax at 50% 38%, rgba(215,180,74,.10), transparent 70%),
    linear-gradient(rgba(74,168,255,.06) 1px, transparent 1px) 0 0 / 34px 34px,
    linear-gradient(90deg, rgba(74,168,255,.06) 1px, transparent 1px) 0 0 / 34px 34px; }
body::after { content: ""; position: fixed; left: 0; right: 0; top: -30vh; height: 30vh; pointer-events: none; z-index: 0;
  background: linear-gradient(transparent, rgba(74,168,255,.07), transparent); animation: sweep 6s linear infinite; }
@keyframes sweep { to { transform: translateY(160vh); } }
main { position: relative; z-index: 1; max-width: 860px; margin: 0 auto;
  padding: 18px 16px calc(28px + env(safe-area-inset-bottom, 0px)); }

/* the door */
#door { max-width: 340px; margin: 12vh auto 0; display: grid; gap: 14px; justify-items: center; }
.ring { position: relative; width: 168px; height: 168px; margin-bottom: 6px; }
.ring svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.ring .outer { animation: spin 18s linear infinite; transform-origin: 50% 50%; }
.ring .inner { animation: spin 9s linear infinite reverse; transform-origin: 50% 50%; }
.ring .core { filter: drop-shadow(0 0 10px rgba(215,180,74,.55)); transition: transform .4s; }
@keyframes spin { to { transform: rotate(360deg); } }
#door.busy .outer { animation-duration: 2s; } #door.busy .inner { animation-duration: 1s; }
#door.no .ring { animation: shake .4s; } #door.no .ring svg { --c: var(--bad); }
#door.no .core { filter: drop-shadow(0 0 12px rgba(255,107,91,.8)); }
@keyframes shake { 20%,60% { transform: translateX(-8px); } 40%,80% { transform: translateX(8px); } }
#door.yes .ring { animation: lift .6s forwards; }
@keyframes lift { to { transform: scale(1.6); opacity: 0; } }
.tag { font: 600 11px/1 var(--mono); letter-spacing: .32em; color: var(--dim); text-transform: uppercase; }
.tag i { display: inline-block; width: 6px; height: 6px; margin-right: 8px; border-radius: 50%; background: var(--gold);
  box-shadow: 0 0 8px var(--gold); animation: blink 1.6s steps(2) infinite; font-style: normal; }
@keyframes blink { 50% { opacity: .2; } }
.field { position: relative; width: 100%; }
input[type=password] { width: 100%; padding: 14px 14px; font: 16px/1 var(--mono); letter-spacing: .12em; color: var(--ink);
  background: rgba(11,15,23,.85); border: 1px solid var(--line); border-radius: 2px; outline: none;
  clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px); }
input[type=password]:focus { border-color: var(--gold); box-shadow: inset 0 0 0 1px rgba(215,180,74,.35), 0 0 18px rgba(215,180,74,.15); }
button { width: 100%; padding: 14px; font: 700 13px/1 var(--mono); letter-spacing: .34em; text-transform: uppercase;
  color: var(--bg); background: linear-gradient(90deg, #b8932d, var(--gold), #f0d27a); border: 0; cursor: pointer;
  clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px); }
button:hover { filter: brightness(1.1); } button[disabled] { opacity: .55; }
label { display: flex; gap: 8px; align-items: center; color: var(--dim); font-size: 13px; justify-self: start; }
input[type=checkbox] { accent-color: var(--gold); }
#say { min-height: 1.4em; color: var(--bad); font: 12px/1.4 var(--mono); letter-spacing: .1em; text-align: center; }

/* inside */
#card { display: none; animation: rise .5s ease-out; }
@keyframes rise { from { opacity: 0; transform: translateY(14px); } }
#bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 0 12px;
  font: 11px/1 var(--mono); letter-spacing: .18em; text-transform: uppercase; color: var(--dim); }
#bar .live { color: var(--gold); } #bar .live::before { content: "\\25CF  "; color: #3ddc84; }
#shut { color: var(--blue); text-decoration: none; border: 1px solid rgba(74,168,255,.4); padding: 7px 10px; }
#shut:hover { background: rgba(74,168,255,.12); }
#tabs { display: flex; gap: 2px; margin: 0 0 14px; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid var(--line); }
#tabs::-webkit-scrollbar { display: none; }
#tabs button { width: auto; flex: 0 0 auto; padding: 11px 14px 10px; clip-path: none; background: none; color: var(--dim);
  font: 600 12px/1 var(--mono); letter-spacing: .2em; border-bottom: 2px solid transparent; }
#tabs button[aria-selected=true] { color: var(--ink); border-bottom-color: var(--blue);
  background: linear-gradient(transparent 40%, rgba(74,168,255,.10)); }
.room { display: none; } .room.on { display: block; animation: rise .3s ease-out; }
.sheet { background: #fff; color: #111827; padding: 6px 14px 14px; overflow-x: auto;
  border-top: 2px solid var(--gold); box-shadow: 0 0 0 1px var(--line), 0 18px 50px rgba(0,0,0,.5); }
.panel { background: rgba(11,15,23,.88); border: 1px solid var(--line); border-top: 2px solid var(--gold); padding: 14px; }
.panel h3 { margin: 18px 0 8px; font: 600 11px/1 var(--mono); letter-spacing: .24em; text-transform: uppercase; color: var(--gold); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }
.tile { border: 1px solid var(--line); padding: 12px; background: rgba(5,7,11,.6); }
.tile b { display: block; font: 600 22px/1.1 var(--mono); color: var(--ink); }
.tile span { display: block; margin-top: 6px; font: 10px/1 var(--mono); letter-spacing: .2em; text-transform: uppercase; color: var(--dim); }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px; font: 600 10px/1.2 var(--mono); letter-spacing: .16em; text-transform: uppercase;
  color: var(--dim); border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 8px; border-bottom: 1px solid rgba(28,36,51,.6); }
td.n, th.n { text-align: right; font-family: var(--mono); white-space: nowrap; }
tbody tr:hover { background: rgba(74,168,255,.07); }
.note { color: var(--dim); font-size: 12px; margin: 12px 0 0; }
.call { margin: 0 0 12px; font-size: 16px; color: var(--ink); border-left: 2px solid var(--blue); padding-left: 10px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; } }
</style></head><body><main>
<form id="door" autocomplete="off">
  <div class="ring" aria-hidden="true">
    <svg viewBox="0 0 168 168" style="--c: var(--gold)">
      <g class="outer" fill="none" stroke="var(--c, #d7b44a)" stroke-width="1.5">
        <circle cx="84" cy="84" r="80" stroke-dasharray="3 7" opacity=".55"/>
        <path d="M84 2v12M84 154v12M2 84h12M154 84h12" stroke-width="2"/>
      </g>
      <g class="inner" fill="none" stroke="#4aa8ff" stroke-width="2">
        <circle cx="84" cy="84" r="62" stroke-dasharray="80 18 6 18" opacity=".8"/>
      </g>
      <g class="core" fill="none" stroke="var(--c, #d7b44a)" stroke-width="3" stroke-linecap="round">
        <path d="M68 78v-10a16 16 0 0 1 32 0v10"/>
        <rect x="60" y="78" width="48" height="36" rx="4"/>
        <path d="M84 92v8"/>
      </g>
    </svg>
  </div>
  <div class="tag"><i></i>Authorized access</div>
  <div class="field"><input id="pass" type="password" placeholder="Passphrase" autocomplete="current-password" autofocus></div>
  <label><input id="keep" type="checkbox"> Remember on this device</label>
  <button id="go" type="submit">Unlock</button>
  <div id="say" role="status"></div>
</form>
<section id="card"><div id="bar"><span class="live" id="when"></span><a href="#" id="shut">Lock</a></div>
<nav id="tabs" role="tablist"></nav><div id="rooms"></div></section>
</main>
<script>
(function () {
  "use strict";
  var BOX = __BOX__;
  var KEPT = "locker-pass", ROOM = "locker-room";
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
  function pick(id) {
    var tabs = document.querySelectorAll("#tabs button"), rooms = document.querySelectorAll(".room");
    for (var i = 0; i < tabs.length; i++) tabs[i].setAttribute("aria-selected", tabs[i].getAttribute("data-room") === id ? "true" : "false");
    for (var j = 0; j < rooms.length; j++) rooms[j].className = "room" + (rooms[j].id === "room-" + id ? " on" : "");
    try { localStorage.setItem(ROOM, id); } catch (e) { /* private mode */ }
  }
  function show(inside) {
    var all = [{ id: "card", name: "Card", html: inside.html, sheet: true }].concat(inside.rooms || []);
    var tabs = document.getElementById("tabs"), rooms = document.getElementById("rooms");
    all.forEach(function (room) {
      var tab = document.createElement("button");
      tab.type = "button"; tab.setAttribute("role", "tab"); tab.setAttribute("data-room", room.id);
      tab.textContent = room.name;
      tab.addEventListener("click", function () { pick(room.id); });
      tabs.appendChild(tab);
      var box = document.createElement("div");
      box.id = "room-" + room.id; box.className = "room";
      box.innerHTML = '<div class="' + (room.sheet ? "sheet" : "panel") + '">' + room.html + "</div>";
      rooms.appendChild(box);
    });
    if (all.length < 2) tabs.style.display = "none";
    var last = null;
    try { last = localStorage.getItem(ROOM); } catch (e) { /* private mode */ }
    pick(all.some(function (r) { return r.id === last; }) ? last : "card");
    var made = new Date(inside.made * 1000);
    document.getElementById("when").textContent = "As of " + made.toLocaleString("en-US",
      { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    door.className = "yes";
    setTimeout(function () {
      door.style.display = "none";
      card.style.display = "block";
      document.documentElement.setAttribute("data-open", "1");
    }, 450);
  }
  function attempt(phrase, quiet) {
    go.disabled = true;
    door.className = "busy";
    say.textContent = quiet ? "" : "Verifying\\u2026";
    return open(phrase).then(function (inside) {
      try { if (keep.checked) localStorage.setItem(KEPT, phrase); } catch (e) { /* private mode */ }
      show(inside);
    }).catch(function (err) {
      go.disabled = false;
      door.className = "";
      if (quiet) { try { localStorage.removeItem(KEPT); } catch (e) { /* nothing kept */ } say.textContent = ""; return; }
      void door.offsetWidth;
      door.className = "no";
      say.textContent = err && err.message === "old" ? "This browser is too old to open it." : "Access denied.";
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


def page(inside_html: str, passphrase: str, *, made: float | None = None, rooms: list | None = None,
         **fixed) -> str:
    """The whole locked page: `inside_html` (and any further `rooms`, see
    lockedextras.py) scrambled, and the door to it."""
    inside = json.dumps({"html": inside_html, "made": time.time() if made is None else made,
                         "rooms": rooms or []})
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


def put(inside_html: str, *, season=None, now: float | None = None, opener=None) -> str | None:
    """Lock `inside_html` and upload it, when a passphrase is set and the
    card has changed since the last upload. Returns the page's address, or
    None when there was nothing to do. With `season`, the other rooms
    (lockedextras.py) go in beside the card."""
    from . import lockedextras, webpublish
    settings = LockedSettings.load()
    web = webpublish.WebSettings.load()
    if not settings.ready or not web.ready:
        return None
    rooms = lockedextras.rooms(season) if season is not None else []
    mark = hashlib.sha256((settings.sealed_passphrase + "\0" + inside_html + "\0"
                           + json.dumps(rooms, sort_keys=True)).encode("utf-8")).hexdigest()
    if mark == settings.shown:
        return None
    try:
        passphrase = unseal(settings.sealed_passphrase)
    except Exception as exc:  # noqa: BLE001 - sealed on another Windows account
        raise LockedPageError("The private page's passphrase can't be read on this account - set it again.") from exc
    body = page(inside_html, passphrase, made=now, rooms=rooms).encode("utf-8")
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
    return put(inside, season=season, now=now, opener=opener) if inside else None


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
