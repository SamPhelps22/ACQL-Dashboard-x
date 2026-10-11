"""The league's logo, for the website's header and the home-screen icon.

One file is kept - brand/acql-logo.png, the logo cut out of its background
at 512 pixels - and everything else is made from it as it is needed: a small
copy written into the page itself (so the page still shows it when it is
saved as one file, or opened with no signal), and the square icons a phone
puts on its home screen.

Everything here returns nothing rather than failing when the file or Pillow
isn't there: the page then draws its old crest, and the site still goes up.
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache
from pathlib import Path

LOGO = Path(__file__).with_name("brand") / "acql-logo.png"
#: The colour behind the icon: the logo's own black.
ICON_GROUND = (9, 11, 10)
#: How much of an icon the logo fills. Phones cut icons into circles and
#: rounded squares; inside the middle four-fifths nothing is ever clipped.
ICON_FILL = 0.82
#: The copy written into the page, in pixels: sharp in the header on any
#: phone, and good enough for the big faint one behind the headline.
PAGE_SIZE = 256


def _open():
    from PIL import Image
    return Image.open(LOGO).convert("RGBA")


@lru_cache(maxsize=4)
def data_uri(size: int = PAGE_SIZE) -> str:
    """The logo as a data: address for the page, or "" when it can't be made."""
    try:
        from PIL import Image
        logo = _open().resize((size, size), Image.LANCZOS)
        out = io.BytesIO()
        logo.save(out, format="WEBP", quality=80, method=6)
        return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - no file, or no Pillow: the page draws its crest
        return ""


def image(size: int = 220):
    """The logo as a picture for the link-preview card, or None."""
    try:
        from PIL import Image
        return _open().resize((size, size), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


def icon(size: int = 512) -> bytes | None:
    """The home-screen icon: the logo on its own black, as a square PNG."""
    try:
        from PIL import Image
        inner = round(size * ICON_FILL)
        logo = _open().resize((inner, inner), Image.LANCZOS)
        square = Image.new("RGBA", (size, size), (*ICON_GROUND, 255))
        square.alpha_composite(logo, ((size - inner) // 2, (size - inner) // 2))
        out = io.BytesIO()
        square.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None
