"""Email the weekly recap, one click, through the sender's own Gmail.

Gmail will not let an app sign in with an account's normal password. It
issues an *app password* instead - 16 letters, made at
https://myaccount.google.com/apppasswords once 2-Step Verification is on -
which can send mail and nothing else, and can be revoked at any time from
the same page without touching the real password.

The settings live beside the pool's data in acql-email.json. On Windows the
app password is sealed with the Windows data-protection API (DPAPI), which
ties it to the signed-in Windows account: the file alone, copied to another
machine or read by another user, does not reveal it. Everything here is the
standard library; nothing extra to install.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import smtplib
import ssl
import sys
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465
TIMEOUT = 25
SETTINGS_NAME = "acql-email.json"
APP_PASSWORD_PAGE = "https://myaccount.google.com/apppasswords"


def _settings_path() -> Path:
    try:
        from .config import DATA_DIR  # lazy: config never imports this
        return Path(DATA_DIR) / SETTINGS_NAME
    except Exception:  # noqa: BLE001
        return Path.home() / ".acql" / SETTINGS_NAME


# ---- keeping the app password out of plain sight -------------------------
def _dpapi(data: bytes, protect: bool) -> bytes:
    """Seal or unseal bytes with the Windows account's own key."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = call(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(result))
    if not ok:
        raise OSError("Windows could not " + ("seal" if protect else "open") + " the password")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def seal(secret: str) -> str:
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
        except Exception:  # noqa: BLE001 - never lose the setting over this
            pass
    # Only scrambled, not locked: used off Windows, or if Windows refuses.
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unseal(stored: str) -> str:
    if not stored:
        return ""
    kind, _, body = stored.partition(":")
    raw = base64.b64decode(body.encode("ascii"))
    if kind == "dpapi":
        return _dpapi(raw, False).decode("utf-8")
    return raw.decode("utf-8")


# ---- settings -------------------------------------------------------------
@dataclass
class MailSettings:
    sender: str = ""                     # the Gmail address it sends from
    recipients: list[str] = field(default_factory=list)
    sealed_password: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.sender and self.recipients and self.sealed_password)

    @property
    def password(self) -> str:
        return unseal(self.sealed_password)

    def set_password(self, app_password: str) -> None:
        # Google shows it as four groups of four; the spaces are not part of it.
        self.sealed_password = seal("".join(app_password.split()))

    @classmethod
    def load(cls) -> MailSettings:
        try:
            raw = json.loads(_settings_path().read_text(encoding="utf-8"))
            return cls(
                sender=str(raw.get("sender", "")),
                recipients=[str(r) for r in raw.get("recipients", []) if str(r).strip()],
                sealed_password=str(raw.get("sealed_password", "")),
            )
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")


def parse_recipients(text: str) -> list[str]:
    """"a@x.com, b@y.com; c@z.com" -> three addresses."""
    parts = [p.strip() for chunk in text.replace(";", ",").split(",") for p in chunk.split()]
    return [p for p in parts if "@" in p and "." in p.split("@")[-1]]


# ---- the message ---------------------------------------------------------
def build_message(settings: MailSettings, image: Path, subject: str, summary: str) -> EmailMessage:
    """The recap as an email: a short text body, the picture in line and attached."""
    msg = EmailMessage()
    msg["From"] = settings.sender
    msg["To"] = ", ".join(settings.recipients)
    msg["Subject"] = subject
    msg.set_content(summary + "\n\nThe recap picture is attached.\n\n- ACQL Dashboard")
    data = Path(image).read_bytes()
    cid = "recap-image"
    msg.add_alternative(
        f"<p style='font-family:Segoe UI,Arial,sans-serif;font-size:15px'>"
        f"{summary.replace(chr(10), '<br>')}</p>"
        f"<img src='cid:{cid}' alt='Weekly recap' style='max-width:100%;width:540px'>"
        f"<p style='font-family:Segoe UI,Arial,sans-serif;color:#888;font-size:12px'>"
        f"ACQL Dashboard</p>",
        subtype="html",
    )
    maintype, subtype = (mimetypes.guess_type(image.name)[0] or "image/png").split("/")
    msg.get_payload()[1].add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>")
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(image).name)
    return msg


def send(settings: MailSettings, message: EmailMessage, *, smtp_factory=None) -> None:
    """Send through Gmail. Raises MailError with a plain-English reason."""
    factory = smtp_factory or (
        lambda: smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, timeout=TIMEOUT,
                                 context=ssl.create_default_context())
    )
    try:
        with factory() as server:
            server.login(settings.sender, settings.password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Gmail turned down the sign-in. It needs an app password, not your "
            f"normal one - make one at {APP_PASSWORD_PAGE} and enter it under "
            "“Email settings”."
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Couldn't reach Gmail to send it ({exc}). Check the connection and try again.") from exc


class MailError(Exception):
    """A send that failed, with a reason fit to show the person."""
