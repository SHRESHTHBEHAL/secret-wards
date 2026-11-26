"""Devanagari -> Latin transliteration and cross-script name matching. Pure, standard library only."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from raksha.normalize import norm_text
from raksha.scripts import fold

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "ऩ": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ऱ": "r", "ल": "l", "ळ": "l", "ऴ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y"}
_INDEP = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ॠ": "ri",
    "ऌ": "li", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e", "ऎ": "e", "ऒ": "o",
}
_MATRA = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "ॄ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e", "ॆ": "e", "ॊ": "o",
}
_VIRAMA = "्"
_NUKTA_SIGN = "़"
_ANUSVARA = "ं"
_CHANDRA = "ँ"
_VISARGA = "ः"
_LABIALS = ("p", "b", "m")


def is_deva(s: str) -> bool:
    """True when `s` holds at least one Devanagari letter."""
    for c in s:
        if "ऀ" <= c <= "ॿ" and unicodedata.category(c) == "Lo":
            return True
    return False


def _deva_word(w: str) -> str:
    # units: [latin_consonant_or_None, vowel, nasal_suffix]
    units = []  # type: List[List[str]]
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        if c in _CONS:
            lat = _CONS[c]
            if i + 1 < n and w[i + 1] == _NUKTA_SIGN:
                lat = _NUKTA.get(c, lat)
                i += 1
            vowel = "a"
            if i + 1 < n:
                nx = w[i + 1]
                if nx == _VIRAMA:
                    vowel = ""
                    i += 1
                elif nx in _MATRA:
                    vowel = _MATRA[nx]
                    i += 1
            units.append([lat, vowel, ""])
        elif c in _INDEP:
            units.append(["", _INDEP[c], ""])
        elif c in (_ANUSVARA, _CHANDRA):
            if units:
                units[-1][2] = "n"
            else:
                units.append(["", "", "n"])
        elif c == _VISARGA:
            if units:
                units[-1][2] += "h"
        elif c == "ॐ":
            units.append(["", "o", "m"])
        elif c in (_NUKTA_SIGN, _VIRAMA):
            pass
        else:
            units.append(["", "", c])
        i += 1
    m = len(units)
    if m == 0:
        return ""
    # word-final schwa
    last = units[-1]
    if last[0] and last[1] == "a" and not last[2] and m > 1:
        last[1] = ""
    # medial schwa deletion: V C(a) C V  ->  V C C V
    for k in range(1, m - 1):
        u = units[k]
        if not u[0] or u[1] != "a" or u[2]:
            continue
        prev, nxt = units[k - 1], units[k + 1]
        if not prev[1] or prev[2]:
            continue
        if not nxt[0] or not nxt[1]:
            continue
        if k + 1 == m - 1 and nxt[1] == "":
            continue
        u[1] = ""
    out = []
    for k, (con, vow, nas) in enumerate(units):
        out.append(con)
        out.append(vow)
        if nas == "n" or nas.startswith("n"):
            nxt_con = units[k + 1][0] if k + 1 < m else ""
            if nxt_con[:1] in _LABIALS and nxt_con:
                out.append("m")
            elif nxt_con == "h":
                out.append("ng")  # सिंह -> singh
            else:
                out.append("n")
            out.append(nas[1:])
        else:
            out.append(nas)
    return "".join(out)


_DEVA_RUN = re.compile("[ऀ-ॣ॰-ॿ]+")


def deva_to_latin(s: str) -> str:
    """Rule-based Devanagari -> lowercase Latin; other characters pass through unchanged."""
    s = unicodedata.normalize("NFC", s.replace("‌", "").replace("‍", ""))
    return _DEVA_RUN.sub(lambda m: _deva_word(m.group(0)), s)


HONORIFICS = frozenset({
    "shri", "shree", "sri", "sh", "smt", "shrimati", "srimati", "sushri", "kum", "ku", "km",
    "mr", "mrs", "ms", "miss", "mister", "master", "baby", "late", "swargiya", "ji", "jee",
    "sahab", "saheb", "janab", "sri.",
    "श्री", "श्रीमती", "सुश्री", "कु", "कुं", "स्व", "स्वर्गीय", "जी", "साहब", "जनाब", "बेबी", "मास्टर",
    "पुत्र", "पुत्री", "पत्नी", "पति",
})
TITLES = frozenset({
    "dr", "doctor", "prof", "professor", "er", "engr", "adv", "advocate", "capt", "col", "maj",
    "lt", "gen", "hon", "sir", "madam", "nurse", "sr", "sis",
    "डॉ", "डा", "डॉक्टर", "प्रो", "इंजी", "एड", "कैप्टन",
})
GENERIC_NAME_PARTS = frozenset({
    "kumar", "kumari", "devi", "lal", "prasad", "singh", "kaur", "bai", "bano", "begum",
    "khatoon", "khatun", "ram", "chand", "nath", "das", "rani", "ben", "bhai", "mohammad",
    "कुमार", "कुमारी", "देवी", "लाल", "प्रसाद", "सिंह", "कौर", "बाई", "बानो", "बेगम", "खातून",
    "राम", "चंद", "चन्द", "नाथ", "दास", "रानी", "बेन", "भाई", "मोहम्मद",
})
_MOHAMMAD = frozenset({"md", "mohd", "mohammed", "muhammad", "mohammad", "muhammed", "mohamad",
                       "मोहम्मद", "मो", "मोह", "मुहम्मद", "मोहम्मद"})
_DROP = frozenset({w.casefold() for w in HONORIFICS | TITLES})
_RELATION = re.compile(r"(?<![a-z])[sdwch]\s*/\s*o(?![a-z])")
_TOKEN = re.compile("[a-z0-9ऀ-ॣ०-ॿ]+")


def name_tokens(name: str) -> List[str]:
    """Lowercase Latin name tokens with titles/honorifics removed and Mohammad variants unified."""
    if not name:
        return []
    t = _RELATION.sub(" ", norm_text(name))
    out = []  # type: List[str]
    for tok in _TOKEN.findall(t):
        if tok in _DROP:
            continue
        if tok in _MOHAMMAD:
            out.append("mohammad")
            continue
        if is_deva(tok):
            tok = deva_to_latin(tok)
            if tok in _MOHAMMAD:
                out.append("mohammad")
                continue
        if tok in _DROP or not tok:
            continue
        out.append(tok)
    return out


_KEY_RULES = (
    ("chh", "c"), ("ch", "c"), ("sh", "s"), ("ph", "f"), ("x", "ks"),
    ("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"),
    ("aya", "ai"), ("ai", "e"), ("au", "o"), ("ow", "o"), ("w", "v"), ("z", "j"), ("q", "k"), ("y", "i"),
)
_H_AFTER_CONS = re.compile(r"([bcdfgjklmnpqrstvxz])h")
_DOUBLE = re.compile(r"(.)\1+")
_NON_ALPHA = re.compile(r"[^a-z]")


@lru_cache(maxsize=262144)
def name_key(token: str) -> str:
    """Phonetic key of a single name token (Latin, Devanagari or any folded Indian script)."""
    t = fold(token)
    if is_deva(t):
        t = deva_to_latin(t)
    t = _NON_ALPHA.sub("", norm_text(t))
    if not t:
        return ""
    for a, b in _KEY_RULES[:5]:
        t = t.replace(a, b)
    t = _H_AFTER_CONS.sub(r"\1", t)
    for a, b in _KEY_RULES[5:]:
        t = t.replace(a, b)
    t = re.sub(r"m(?=[pb])", "n", t)
    t = _DOUBLE.sub(r"\1", t)
    if len(t) > 2 and t.endswith("h"):
        t = t[:-1]
    if len(t) > 1 and t.endswith("a"):
        t = t[:-1]
    return t


def _edit_distance(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            if v < best:
                best = v
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


_VOWELS = re.compile("[aeiou]")


_VOWEL_RUN = re.compile(r"([aiu])\1+")


def _vowel_norm(k: str) -> str:
    """e/i and o/u merged, vowel runs collapsed: 'perier', 'pereir' -> 'pirir' (spelling slips of
    long vowels / diphthongs in transliterated names)."""
    t = k.replace("e", "i").replace("o", "u")
    t = re.sub(r"[aiu]{2,}", lambda m: m.group(0)[-1] if len(set(m.group(0))) > 1 else m.group(0)[0], t)
    return _VOWEL_RUN.sub(r"\1", t)


def _keys_match(ka: str, kb: str) -> bool:
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    na, nb = _vowel_norm(ka), _vowel_norm(kb)
    if (na, nb) != (ka, kb) and len(_VOWELS.sub("", na)) >= 3 and _keys_match1(na, nb):
        return True
    return _keys_match1(ka, kb)


def _keys_match1(ka: str, kb: str) -> bool:
    if ka == kb:
        return True
    longest = max(len(ka), len(kb))
    if longest <= 6:
        # short names: only a single vowel slip, consonant skeleton identical
        return (_VOWELS.sub("", ka) == _VOWELS.sub("", kb)
                and _edit_distance(ka, kb, 1) <= 1)
    if longest <= 8:
        return _edit_distance(ka, kb, 1) <= 1
    return _edit_distance(ka, kb, 2) <= 2


def same_token(a: str, b: str) -> bool:
    """True when two name tokens (either script) sound like the same name."""
    return _keys_match(name_key(a), name_key(b))


def full_name_key(name: str) -> str:
    """Space-joined sorted keys of the name's tokens."""
    return " ".join(sorted(k for k in (name_key(t) for t in name_tokens(name)) if k))


_GENERIC_KEYS = frozenset(name_key(w) for w in GENERIC_NAME_PARTS)


def _match(short: List[str], long_: List[str], i: int, used: List[bool], hit: bool) -> bool:
    if i == len(short):
        return hit
    for j in range(len(long_)):
        if not used[j] and _keys_match(short[i], long_[j]):
            used[j] = True
            if _match(short, long_, i + 1, used, hit or short[i] not in _GENERIC_KEYS):
                return True
            used[j] = False
    return False


def same_name(a: str, b: str) -> bool:
    """Every token of the shorter name matches a distinct token of the longer, one non-generic."""
    ka = [k for k in (name_key(t) for t in name_tokens(a)) if k]
    kb = [k for k in (name_key(t) for t in name_tokens(b)) if k]
    if not ka or not kb:
        return False
    if len(ka) > len(kb):
        ka, kb = kb, ka
    if len(ka) > 8:
        return False
    return _match(ka, kb, 0, [False] * len(kb), False)
