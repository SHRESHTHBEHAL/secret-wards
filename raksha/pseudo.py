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


class ShiftBook:
    """Per-patient date shifts with no two patients on the same offset (while offsets remain).

    The targeted attack (docs/ATTACKS.md, A5) un-shifts the whole release as soon as two re-identified people
    agree on one offset. Independent keyed offsets from ~300 values collide by the birthday paradox; here each key
    starts at its own keyed offset and walks a keyed permutation to the next free one. Deterministic: keys are
    placed in HMAC order, never input order, and unknown keys are placed on first use in sorted file order.
    """

    def __init__(self, keys: "Keys", patient_keys, max_days: int = 180, min_days: int = 30) -> None:
        self._keys = keys
        self.min_days = max(1, int(min_days))
        self.max_days = max(self.min_days, int(max_days))
        self._offsets = [d for d in range(-self.max_days, self.max_days + 1) if abs(d) >= self.min_days]
        self._index = {d: i for i, d in enumerate(self._offsets)}
        self._load = {}  # type: dict
        self._of = {}  # type: dict
        for k in sorted(set(patient_keys), key=lambda k: _mac(keys._k_shift, "order\x00" + k)):
            self.get(k)

    def get(self, key: str) -> int:
        if key in self._of:
            return self._of[key]
        n = len(self._offsets)
        base = self._keys.shift_days(key, self.max_days, self.min_days)
        i = self._index.get(base, 0)
        step = 1 + int.from_bytes(_mac(self._keys._k_shift, "step\x00" + key)[:4], "big") % max(1, n - 1)
        while n > 1 and _gcd(step, n) != 1:
            step += 1
        floor = min(self._load.get(d, 0) for d in self._offsets)
        for _ in range(n):
            d = self._offsets[i]
            if self._load.get(d, 0) <= floor:
                break
            i = (i + step) % n
        d = self._offsets[i]
        self._load[d] = self._load.get(d, 0) + 1
        self._of[key] = d
        return d


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a
