"""Text normalisation and hidden-payload decoding. Pure functions, standard library only."""
from __future__ import annotations

import base64
import binascii
import html
import re
import unicodedata
from typing import List, Optional
from urllib.parse import unquote

from .scripts import fold

# Every non-ASCII decimal digit (Devanagari, Bengali, Gurmukhi, Gujarati, Tamil, ... ) -> ASCII.
_DIGIT_TABLE = {}
for _cp in range(0x80, 0x10000):
    _ch = chr(_cp)
    if unicodedata.category(_ch) == "Nd":
        _DIGIT_TABLE[_cp] = str(unicodedata.decimal(_ch))
del _cp, _ch

_INVISIBLE = {cp: None for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F)}
_LATIN_MARKS = re.compile("[̀-ͯ]")


def to_ascii_digits(s: str) -> str:
    """Indic (and any other Unicode decimal) digits to ASCII 0-9."""
    return s.translate(_DIGIT_TABLE)


def norm_text(s: str) -> str:
    """NFKC, invisible chars removed, digits to ASCII, Latin diacritics stripped, casefolded."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).translate(_INVISIBLE)
    s = fold(s)  # Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam, Urdu -> Devanagari
    s = to_ascii_digits(s)
    s = unicodedata.normalize("NFD", s)
    s = _LATIN_MARKS.sub("", s)
    s = unicodedata.normalize("NFC", s)
    return s.casefold()


def digits_only(s: str) -> str:
    """Only the ASCII digits of `s` after Indic digit conversion."""
    return "".join(c for c in to_ascii_digits(s) if "0" <= c <= "9")


def _printable_ratio(t: str) -> float:
    if not t:
        return 0.0
    ok = sum(1 for c in t if c.isprintable() or c in "\n\r\t")
    return ok / len(t)


def _bytes_to_text(raw: bytes) -> Optional[str]:
    if len(raw) < 4:
        return None
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _printable_ratio(t) < 0.9:
        return None
    # require some letters or digits so random punctuation does not count
    if sum(1 for c in t if c.isalnum()) < max(2, len(t) // 3):
        return None
    return t


_B64_CHARS = re.compile(r"^[A-Za-z0-9+/_\-]+={0,2}$")


def try_b64_text(s: str) -> Optional[str]:
    """Decoded text if `s` (len >= 16) is base64 of mostly printable UTF-8, else None."""
    s = s.strip()
    if len(s) < 16 or not _B64_CHARS.match(s):
        return None
    body = s.rstrip("=")
    if len(body) % 4 == 1:
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        if "-" in body or "_" in body:
            raw = base64.urlsafe_b64decode(padded)
        else:
            raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None
    return _bytes_to_text(raw)


_B64_RUN = re.compile(r"[A-Za-z0-9+/_\-]{16,}={0,2}")
_HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){8,}(?![0-9A-Fa-f])")
_PCT = re.compile(r"%[0-9A-Fa-f]{2}")
_UESC = re.compile(r"\\u([0-9A-Fa-f]{4})")
_ENTITY = re.compile(r"&(#\d+|#[xX][0-9A-Fa-f]+|[A-Za-z]+);")


def _decode_once(s: str) -> List[str]:
    out = []  # type: List[str]
    for m in _B64_RUN.finditer(s):
        run = m.group(0)
        if re.fullmatch(r"[0-9]+", run) or re.fullmatch(r"[0-9A-Fa-f]+", run):
            continue  # plain numbers / hex are handled elsewhere
        t = try_b64_text(run)
        if t is not None:
            out.append(t)
    for m in _HEX_RUN.finditer(s):
        run = m.group(0)
        if run.isdigit():
            continue
        t = _bytes_to_text(bytes.fromhex(run))
        if t is not None:
            out.append(t)
    if _PCT.search(s):
        try:
            t = unquote(s, errors="strict")
        except UnicodeDecodeError:
            t = unquote(s, errors="replace")
        if t != s:
            out.append(t)
    if _UESC.search(s):
        t = _UESC.sub(lambda m: chr(int(m.group(1), 16)), s)
        # join surrogate pairs if any
        try:
            t = t.encode("utf-16", "surrogatepass").decode("utf-16")
        except UnicodeError:
            pass
        if t != s:
            out.append(t)
    if _ENTITY.search(s):
        t = html.unescape(s)
        if t != s:
            out.append(t)
    return out


def decode_layers(s: str) -> List[str]:
    """Decoded payloads hidden in `s` (base64, hex, %XX, \\uXXXX, HTML entities), nested up to 3 deep."""
    if not s:
        return []
    found = []  # type: List[str]
    seen = {s}
    frontier = [s]
    for _ in range(3):
        nxt = []  # type: List[str]
        for cur in frontier:
            for t in _decode_once(cur):
                if t not in seen:
                    seen.add(t)
                    found.append(t)
                    nxt.append(t)
        if not nxt:
            break
        frontier = nxt
    return found
