"""Normalised keys used to recognise the same book across servers and files."""

from __future__ import annotations

import re
import unicodedata

LEADING_ARTICLES = {"the", "a", "an"}
_AUTHOR_SPLIT = re.compile(r"\s*(?:&|;|\band\b|\bwith\b)\s*", re.I)


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", text)


def normalize_title(title: str) -> str:
    tokens = _tokens(title)
    if len(tokens) > 1 and tokens[0] in LEADING_ARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens)


def normalize_authors(authors: list[str]) -> str:
    """Order-independent key: 'Doe, Jane & John Roe' == 'John Roe & Jane Doe'."""
    names: list[str] = []
    for entry in authors:
        for name in _AUTHOR_SPLIT.split(entry or ""):
            tokens = sorted(_tokens(name))
            if tokens:
                names.append(" ".join(tokens))
    return " & ".join(sorted(set(names)))


def title_key(authors: list[str], title: str) -> str | None:
    """Return 'authors|title', or None when either part is missing or unknown."""
    a = normalize_authors(authors)
    t = normalize_title(title)
    if not a or not t or a in {"unknown", "author unknown"} or t == "unknown":
        return None
    return f"{a}|{t}"


def normalize_format(ext: str) -> str:
    ext = (ext or "").lower().lstrip(".")
    return {"kepub.epub": "kepub", "fb2.zip": "fb2", "prc": "mobi"}.get(ext, ext)


def isbn13(isbn: str) -> str | None:
    """Convert an ISBN-10 or ISBN-13 to a validated ISBN-13, or None if invalid."""
    s = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    if len(s) == 10:
        if not s[:9].isdigit() or not (s[9].isdigit() or s[9] == "X"):
            return None
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        if total % 11:
            return None
        core = "978" + s[:9]
    elif len(s) == 13 and s.isdigit():
        core = s[:12]
    else:
        return None
    check = (10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(core)) % 10) % 10
    full = core + str(check)
    if len(s) == 13 and full != s:
        return None
    return full
