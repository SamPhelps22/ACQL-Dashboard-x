"""Fit the stream's window into RedZone mode's gap (Windows only).

Finds the open window playing RedZone by its title (Spectrum, YouTube TV,
NFL+...), takes it out of maximised, and moves it so its inside - not its
title bar - fills the gap exactly; the title bar tucks under the scores bar.
Nothing here works when the player itself is in full screen: that has to be
left first (Esc or the player's full-screen button).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

#: Title words that mark a window playing the stream, most likely first.
#: The streaming services come first: a tab merely named "RedZone" is not the stream.
KEYWORDS = ("spectrum", "youtube tv", "nfl+", "nfl plus", "sunday ticket", "redzone", "red zone", "nfl")


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _titles() -> list[tuple[int, str]]:
    user = ctypes.windll.user32
    found: list[tuple[int, str]] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
            n = user.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user.GetWindowTextW(hwnd, buf, n + 1)
                found.append((hwnd, buf.value))
        return True
    user.EnumWindows(proto(visit), 0)
    return found


#: Where Spectrum's live TV opens.
SPECTRUM_URL = "https://watch.spectrum.net/livetv"


def chrome_path() -> str | None:
    import os
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path
    return None


def open_spectrum() -> bool:
    """Spectrum in a bare Chrome window: no tabs, address bar or bookmarks."""
    import subprocess
    chrome = chrome_path()
    if chrome is None:
        return False
    subprocess.Popen([chrome, f"--app={SPECTRUM_URL}"])
    return True


#: Our own windows and the website's "open RedZone" helper tab - never the stream.
SKIP = ("ACQL", "Operation Sunday", "Opening RedZone")


def _helper_tab(title: str) -> bool:
    """The Lab's /redzone page, as titled before it said so (just "RedZone")."""
    return title.split(" - ")[0].strip().lower() == "redzone"


def find_stream(skip: tuple[str, ...] = SKIP) -> tuple[int, str] | None:
    """The window most likely playing the stream, or None. A bare (app) window
    beats a Chrome window with tabs."""
    if sys.platform != "win32":
        return None
    windows = [(h, t) for h, t in _titles()
               if not any(s.lower() in t.lower() for s in skip) and not _helper_tab(t)]
    windows.sort(key=lambda w: w[1].endswith("Google Chrome"))
    for word in KEYWORDS:
        for hwnd, title in windows:
            if word in title.lower():
                return hwnd, title
    return None


def fit(hwnd: int, left: int, top: int, width: int, height: int) -> bool:
    """Move `hwnd` so its inside covers the given screen rectangle (physical pixels)."""
    user = ctypes.windll.user32
    user.ShowWindow(hwnd, 9)                             # SW_RESTORE: out of maximised
    outer, inner = _Rect(), _Rect()
    user.GetWindowRect(hwnd, ctypes.byref(outer))
    user.GetClientRect(hwnd, ctypes.byref(inner))
    corner = wintypes.POINT(0, 0)
    user.ClientToScreen(hwnd, ctypes.byref(corner))
    # how far the inside sits from the window's own edges (title bar, borders)
    dl, dt = corner.x - outer.left, corner.y - outer.top
    dr = (outer.right - outer.left) - dl - (inner.right - inner.left)
    db = (outer.bottom - outer.top) - dt - (inner.bottom - inner.top)
    ok = user.SetWindowPos(hwnd, 0, left - dl, top - dt, width + dl + dr, height + dt + db,
                           0x0040)                        # SWP_SHOWWINDOW, to the top
    # above every ordinary window (the overlay stays above it, being always-on-top)
    for after in (-1, -2):                               # HWND_TOPMOST, then HWND_NOTOPMOST
        user.SetWindowPos(hwnd, after, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # NOSIZE|NOMOVE|NOACTIVATE
    user.SetForegroundWindow(hwnd)
    return bool(ok)
