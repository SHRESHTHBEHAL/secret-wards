"""Keyed pseudonyms and date shifts. Standard library only, Python 3.9+.

The raw secret is only used to derive two subkeys and is never stored.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Iterable

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_LABEL_PSEUDONYM = b"pseudonym-v1"
_LABEL_DATESHIFT = b"dateshift-v1"
_MAX_TRIES = 10000


def _mac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _crockford(data: bytes, n: int) -> str:
    num = int.from_bytes(data, "big")
    bits = len(data) * 8
    out = []
    for i in range(n):
        shift = bits - 5 * (i + 1)
        out.append(CROCKFORD[(num >> shift) & 31])
    return "".join(out)


class Keys:
    """Holds HMAC subkeys derived from a secret; never the secret itself."""

    __slots__ = ("_k_psn", "_k_shift")

    def __init__(self, secret: bytes) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not secret:
            raise ValueError("secret must be non-empty")
        self._k_psn = hmac.new(secret, _LABEL_PSEUDONYM, hashlib.sha256).digest()
        self._k_shift = hmac.new(secret, _LABEL_DATESHIFT, hashlib.sha256).digest()

    def __repr__(self) -> str:
        return "Keys(<hidden>)"

    __str__ = __repr__

    def __reduce__(self):  # refuse pickling of key material
        raise TypeError("Keys cannot be pickled")

    def pseudonym(self, canonical_key: str, forbidden_digits: Iterable[str] = ()) -> str:
        forbidden = sorted({f for f in forbidden_digits if f and len(f) >= 5})
        for counter in range(_MAX_TRIES):
            msg = canonical_key if counter == 0 else "%s\x00%d" % (canonical_key, counter)
            body = _crockford(_mac(self._k_psn, "psn\x00" + msg), 10)
            digits = "".join(c for c in body if c.isdigit())
            if not any(f in body or f in digits for f in forbidden):
                return "PSN-" + body
        raise ValueError("could not derive a pseudonym avoiding forbidden digits")

    def shift_days(self, canonical_key: str, max_days: int = 180, min_days: int = 30) -> int:
        min_days = max(1, int(min_days))
        max_days = int(max_days)
        if max_days < min_days:
            raise ValueError("max_days must be >= min_days")
        span = max_days - min_days + 1
        v = int.from_bytes(_mac(self._k_shift, "shift\x00" + canonical_key), "big") % (2 * span)
        if v < span:
            return min_days + v
        return -(min_days + v - span)

    def opaque(self, tag: str, n: int = 8) -> str:
        if n < 1 or n > 51:
            raise ValueError("n must be in 1..51")
        return _crockford(_mac(self._k_psn, "opaque\x00" + tag), n)
