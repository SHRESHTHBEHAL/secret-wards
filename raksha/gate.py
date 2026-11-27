"""Leak gate: a last independent check that no known identifier survives in an output.

Built from the identity facts the pipeline harvested (never from the raw files). It looks for
digit identifiers across separators and scripts, exact text identifiers, full patient names
(any order, either script) and the same things inside decoded base64 / hex / %XX / \\uXXXX /
HTML-entity payloads. Standard library only, Python 3.9+.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from .lexicon import CLINICAL_WORDS, COMPLAINT_WORDS, DISTRICTS
from .normalize import decode_layers, digits_only, norm_text
from .scripts import fold
from .translit import GENERIC_NAME_PARTS, HONORIFICS, TITLES, deva_to_latin, name_key, name_tokens
from .types import Facts, Patient

Hit = Tuple[int, int, str]

# Lengths of digit identifiers that are flagged anywhere inside a longer number.
_ANYWHERE_LENGTHS = frozenset((10, 12, 14))
_DOCTOR_WORDS = frozenset(("dr", "doctor", "डॉ", "डा", "डाॅ", "डॉक्टर"))
_SKIP_WORDS = GENERIC_NAME_PARTS | HONORIFICS | TITLES | frozenset(("md", "mohd", "mohammed", "muhammad"))
_SKIP_KEYS = frozenset(k for k in (name_key(w) for w in _SKIP_WORDS) if k)
_GENERIC_KEYS = frozenset(k for k in (name_key(w) for w in GENERIC_NAME_PARTS) if k)

# A known village next to one of these words is part of an institution's or an administrative unit's
# name ("CHC Kanwas", "Kanwas block"), which stays.
_PLACE_KEEP_NEAR = frozenset((
    "hospital", "hospitals", "chc", "phc", "uphc", "sdh", "clinic", "dispensary", "medical", "college",
    "nursing", "centre", "center", "kendra", "lab", "labs", "laboratory", "pharmacy", "institute", "trust",
    "district", "dist", "distt", "zila", "jila", "zilla", "block", "tehsil", "tahsil", "taluk", "taluka",
    "mandal", "thana", "station", "ps", "division", "circle", "branch", "unit", "ward",
    "अस्पताल", "चिकित्सालय", "रुग्णालय", "दवाखाना", "हॉस्पिटल", "हास्पिटल", "केंद्र", "केन्द्र", "जिला", "ज़िला", "तहसील", "ब्लॉक", "थाना"))
# Words that say what kind of place follows; they are not part of the place's own name.
_PLACE_CUES = frozenset((
    "vill", "village", "gram", "gaon", "ganv", "gaanv", "pind", "po", "post", "vpo", "at", "tola", "mohalla",
    "near", "the", "of", "and", "ग्राम", "गांव", "गाँव", "पोस्ट"))

_DISTRICT_KEYS = frozenset(k for k in (name_key(w) for w in DISTRICTS) if k)

_DIGIT_RUN = re.compile(r"[0-9](?:[ /._-]{0,2}[0-9])*")
_DIGIT_GROUP = re.compile(r"[0-9]+")
_WORD = re.compile("[a-zऀ-ॣ॰-ॿ]+")
_GAP_OK = re.compile(r"[^\S\n\r]|[.,;:'\"|/()_\-]")
_B64_RUN = re.compile(r"[A-Za-z0-9+/_\-]{16,}={0,2}")
_HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){8,}(?![0-9A-Fa-f])")
_ESC_RUN = re.compile(r"(?:[\w.@+\- ]*(?:%[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}|&#?[0-9A-Za-z]+;))+[\w.@+\- ]*")


@dataclass
class Forbidden:
    digit_cores: FrozenSet[str]
    exact: FrozenSet[str]
    full_names: Tuple[Tuple[str, ...], ...]
    places: Tuple[Tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        self._place_first = {}  # type: Dict[str, List[Tuple[str, ...]]]
        for pl in self.places:
            self._place_first.setdefault(pl[0], []).append(pl)
        for v in self._place_first.values():
            v.sort(key=len, reverse=True)
        self._core_lengths = tuple(sorted({len(c) for c in self.digit_cores}))
        self._exact_rx = _trie_regex(sorted(self.exact)) if self.exact else None
        self._name_sets = frozenset(frozenset(n) for n in self.full_names)
        self._name_keys = frozenset(k for n in self.full_names for k in n)
        self._max_name = max((len(n) for n in self.full_names), default=0)

    def __repr__(self) -> str:  # never print the values
        return "Forbidden(<%d digit, %d exact, %d names>)" % (
            len(self.digit_cores), len(self.exact), len(self.full_names))

    __str__ = __repr__


def _trie_regex(words: Sequence[str]) -> "re.Pattern[str]":
    """One compiled alternation shaped as a prefix trie (fast even with many thousands of words)."""
    trie = {}  # type: Dict[str, dict]
    for w in words:
        node = trie
        for ch in w:
            node = node.setdefault(ch, {})
        node[""] = {}

    def emit(node: Dict[str, dict]) -> str:
        end = "" in node
        alts = []
        for ch in sorted(k for k in node if k):
            alts.append(re.escape(ch) + emit(node[ch]))
        if not alts:
            return ""
        body = alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"
        return "(?:" + body + ")?" if end else body

    return re.compile(emit(trie))


def _id_value(tok: str) -> str:
    if ":" in tok:
        head, rest = tok.split(":", 1)
        if head.isalpha() and head.islower():
            return rest
    return tok


def _person_name(name: str) -> Optional[Tuple[str, ...]]:
    keys = sorted({k for k in (name_key(t) for t in name_tokens(name)) if k and k not in _GENERIC_KEYS})
    return tuple(keys) if len(keys) >= 2 else None


def _place_words(village: str) -> Optional[Tuple[str, ...]]:
    """The words of a village learned from a typed village field, when they are distinctive enough to
    remove wherever they appear: two or more words, or one long word, that is not a district, a
    clinical word or a place-type word."""
    nt, _ = _norm_map(str(village or ""))
    if any(c.isdigit() for c in nt):
        return None
    words = _WORD.findall(nt)
    while words and words[0] in _PLACE_CUES:
        words = words[1:]
    while words and words[-1] in _PLACE_CUES:
        words = words[:-1]
    if not words or len(words) > 5:
        return None
    if any(w in _PLACE_KEEP_NEAR for w in words):
        return None
    for w in words:
        lat = deva_to_latin(w).lower() if not w.isascii() else w
        if w in DISTRICTS or lat in DISTRICTS or name_key(lat) in _DISTRICT_KEYS:
            return None                      # a district is kept by policy, in either script
        if w in CLINICAL_WORDS or w in COMPLAINT_WORDS:
            return None
    if len(words) == 1 and len(words[0]) < 6:
        return None
    if len(words) >= 2 and sum(len(w) for w in words) < 8:
        return None
    return tuple(words)


def forbidden_from_facts(facts: Iterable[Facts]) -> Forbidden:
    cores = set()
    exact = set()
    names = set()
    places = set()
    for f in facts:
        if f is None:
            continue
        for raw in list(f.ids or []) + list(f.raw_ids or []):
            val = _id_value(str(raw))
            d = digits_only(val)
            if len(d) >= 5:
                cores.add(d)
            n = re.sub(r"\s+", "", norm_text(val))
            if len(n) >= 5 and any(c.isalpha() for c in n):
                exact.add(n)
                compact = re.sub(r"[^0-9a-z@]", "", n)
                if len(compact) >= 5 and compact != n and "@" not in n:
                    exact.add(compact)
        for nm in list(f.names or []) + [r[1] for r in (f.relatives or []) if len(r) > 1]:
            key = _person_name(str(nm))
            if key:
                names.add(key)
        pl = _place_words(getattr(f, "village", "") or "")
        if pl:
            places.add(pl)
    return Forbidden(digit_cores=frozenset(cores), exact=frozenset(exact), full_names=tuple(sorted(names)),
                     places=tuple(sorted(places)))


def forbidden_from_book(book: Dict[str, Patient]) -> Forbidden:
    return forbidden_from_facts(f for k in sorted(book) for f in book[k].facts)


# ----------------------------------------------------------------------------- scanning

_CHAR_NORM = {}  # type: Dict[str, str]


def _norm_map(text: str) -> Tuple[str, Optional[List[int]]]:
    """Normalised text plus, for non-ASCII input, the original index of each normalised char."""
    if text.isascii():
        return text.lower(), None
    text = fold(text)  # length-preserving, so the index map below stays valid for the original
    out = []
    idx = []  # type: List[int]
    cache = _CHAR_NORM
    for i, ch in enumerate(text):
        n = cache.get(ch)
        if n is None:
            n = norm_text(ch)
            if len(cache) < 100000:
                cache[ch] = n
        if n:
            out.append(n)
            idx.extend([i] * len(n))
    return "".join(out), idx


def _orig(idx: Optional[List[int]], start: int, end: int, n_orig: int) -> Tuple[int, int]:
    if idx is None:
        return start, end
    s = idx[start] if start < len(idx) else n_orig
    e = idx[end - 1] + 1 if 0 < end <= len(idx) else n_orig
    return s, e


def _digit_hits(nt: str, fb: Forbidden) -> List[Tuple[int, int]]:
    out = []
    cores = fb.digit_cores
    lengths = fb._core_lengths
    if not cores:
        return out
    for m in _DIGIT_RUN.finditer(nt):
        run = m.group(0)
        if len(run) < lengths[0]:
            continue
        base = m.start()
        pos = []
        starts = set()
        ends = set()
        for g in _DIGIT_GROUP.finditer(run):
            starts.add(len(pos))
            pos.extend(range(base + g.start(), base + g.end()))
            ends.add(len(pos) - 1)
        d = "".join(nt[p] for p in pos)
        n = len(d)
        for l in lengths:
            if l > n:
                break
            anywhere = l in _ANYWHERE_LENGTHS
            for k in range(n - l + 1):
                if d[k:k + l] in cores and (anywhere or (k in starts and k + l - 1 in ends)):
                    out.append((pos[k], pos[k + l - 1] + 1))
    return out


def _name_hits(nt: str, fb: Forbidden) -> List[Tuple[int, int]]:
    """Runs of adjacent words whose keys form a known full name. Words are streamed through a
    window of `width` + 1 words, so memory stays flat on a 30 MB text."""
    out = []  # type: List[Tuple[int, int]]
    if not fb._name_sets:
        return out
    all_keys = fb._name_keys
    width = fb._max_name + 3
    it = _WORD.finditer(nt)
    buf = []  # type: List[Tuple[int, int, str, str]]   (start, end, word, key)
    base = 0                                           # global index of buf[0]
    done = False

    def have(g: int) -> bool:                          # word g available (fetching lazily)
        nonlocal done
        while not done and g - base >= len(buf):
            m = next(it, None)
            if m is None:
                done = True
                break
            w = m.group(0)
            buf.append((m.start(), m.end(), w, name_key(w)))
        return g - base < len(buf)

    def adjacent(a: int, b: int) -> bool:
        gap = nt[buf[a - base][1]:buf[b - base][0]]
        return len(gap) <= 3 and all(_GAP_OK.match(c) for c in gap)

    i = 0
    while have(i):
        if i - base > 1:                               # keep word i - 1 for the look-behind
            del buf[:i - 1 - base]
            base = i - 1
        k = buf[i - base][3]
        if k in all_keys:
            cur = {k}
            j = i + 1
            while j < i + width and have(j):
                if not adjacent(j - 1, j):
                    break
                kj = buf[j - base][3]
                if kj in all_keys:
                    cur.add(kj)
                    if len(cur) >= 2 and frozenset(cur) in fb._name_sets:
                        if not (i > 0 and adjacent(i - 1, i) and buf[i - 1 - base][2] in _DOCTOR_WORDS):
                            out.append((buf[i - base][0], buf[j - base][1]))
                elif kj not in _SKIP_KEYS:
                    break
                j += 1
        i += 1
    return out


def _place_hits(nt: str, fb: Forbidden) -> List[Tuple[int, int]]:
    """Known villages written out as whole words, unless the neighbouring word makes them part of an
    institution's or an administrative unit's name."""
    out = []  # type: List[Tuple[int, int]]
    first = fb._place_first
    if not first:
        return out
    ws = [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(nt)]
    i = 0
    while i < len(ws):
        cands = first.get(ws[i][2])
        hit = 0
        if cands:
            for pl in cands:
                n = len(pl)
                if i + n <= len(ws) and all(ws[i + k][2] == pl[k] for k in range(n)) and all(
                        len(nt[ws[i + k][1]:ws[i + k + 1][0]]) <= 3 and "\n" not in nt[ws[i + k][1]:ws[i + k + 1][0]]
                        for k in range(n - 1)):
                    prev = ws[i - 1][2] if i > 0 and "\n" not in nt[ws[i - 1][1]:ws[i][0]] else ""
                    nxt = ws[i + n][2] if i + n < len(ws) and "\n" not in nt[ws[i + n - 1][1]:ws[i + n][0]] else ""
                    if prev in _PLACE_KEEP_NEAR or nxt in _PLACE_KEEP_NEAR or prev in _DOCTOR_WORDS:
                        continue
                    out.append((ws[i][0], ws[i + n - 1][1]))
                    hit = n
                    break
        i += hit or 1
    return out


def _plain(text: str, fb: Forbidden, places: bool = True) -> List[Hit]:
    nt, idx = _norm_map(text)
    n = len(text)
    hits = []  # type: List[Hit]
    for s, e in _digit_hits(nt, fb):
        hits.append(_orig(idx, s, e, n) + ("DIGITS",))
    if fb._exact_rx is not None:
        for m in fb._exact_rx.finditer(nt):
            if m.end() > m.start():
                hits.append(_orig(idx, m.start(), m.end(), n) + ("EXACT",))
    for s, e in _name_hits(nt, fb):
        hits.append(_orig(idx, s, e, n) + ("NAME",))
    if places:                               # not inside encoded payloads: a hit there costs the whole payload
        for s, e in _place_hits(nt, fb):
            hits.append(_orig(idx, s, e, n) + ("PLACE",))
    return hits


def _payload_hit(chunk: str, fb: Forbidden) -> bool:
    return any(_plain(p, fb, places=False) for p in decode_layers(chunk))


def _encoded(text: str, fb: Forbidden) -> List[Hit]:
    if not any(_plain(p, fb, places=False) for p in decode_layers(text)):
        return []
    hits = []  # type: List[Hit]
    for rx in (_B64_RUN, _HEX_RUN, _ESC_RUN):
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            while s < e and text[s] == " ":
                s += 1
            while e > s and text[e - 1] == " ":
                e -= 1
            if e > s and _payload_hit(text[s:e], fb):
                hits.append((s, e, "ENCODED"))
    if not hits:
        hits.append((0, 0, "ENCODED"))
    return hits


def scan(text: str, fb: Forbidden) -> List[Hit]:
    """Leak hits as (start, end, kind) in the original text, sorted.

    Encoded payloads are examined once the plain text is clean (a decoded copy of the whole text
    would otherwise repeat every plain hit). An encoded hit that cannot be located is (0, 0, "ENCODED").
    """
    if not text:
        return []
    hits = _plain(text, fb)
    if not hits:
        hits = _encoded(text, fb)
    return sorted(set(hits))


def _merge(hits: List[Hit]) -> List[Tuple[int, int]]:
    spans = sorted((s, e) for s, e, _ in hits if e > s)
    merged = []  # type: List[List[int]]
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _replace(text: str, spans: List[Tuple[int, int]], placeholder: Any, keep: str) -> str:
    """`placeholder` is a string, or a callable from the leaked segment to its replacement."""
    parts = []
    last = 0
    for s, e in spans:
        parts.append(text[last:s])
        seg = text[s:e]
        if callable(placeholder):
            parts.append(placeholder(seg))
        elif keep:
            pieces = re.split("([" + re.escape(keep) + "])", seg)
            parts.append("".join(p if (p and p in keep) else (placeholder if p else "") for p in pieces))
        else:
            parts.append(placeholder)
        last = e
    parts.append(text[last:])
    return "".join(parts)


def clean(text: str, fb: Forbidden, placeholder: Any = "[REDACTED]", keep: str = "",
          rounds: int = 3) -> Tuple[str, int]:
    """Replace every hit with `placeholder` and re-scan, up to `rounds` times.

    Returns (text, number of hits seen). Characters in `keep` (for example a CSV delimiter and
    quote) are preserved inside replaced spans so the file structure survives. If an encoded hit
    cannot be located the text is returned as it stands: the caller must re-scan and fail closed.
    """
    total = 0
    for _ in range(max(1, rounds)):
        hits = scan(text, fb)
        if not hits:
            break
        total += len(hits)
        spans = _merge(hits)
        if not spans:
            break
        text = _replace(text, spans, placeholder, keep)
    return text, total
