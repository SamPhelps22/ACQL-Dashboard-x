"""Small words the whole app says the same way: counts and places.

No Qt here, and nothing of the pool's - just English.
"""

from __future__ import annotations


def plural(count: int, word: str, many: str = "") -> str:
    """ "1 game", "3 games" - or `many` when the plural isn't an added s ("3 coaches")."""
    return f"{count} {word if count == 1 else (many or word + 's')}"


def suffix(n: int) -> str:
    """The letters after a place: "st", "nd", "rd" or "th"."""
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def ordinal(n: int) -> str:
    """A place in words: "1st", "22nd", "113th"."""
    return f"{n}{suffix(n)}"
