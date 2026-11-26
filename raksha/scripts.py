"""Multi-script support: fold every Indian script onto Devanagari, character for character.

The Brahmic blocks (Bengali/Assamese, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam) share
Devanagari's ISCII-derived layout at a fixed offset, so a consonant, vowel sign or virama in any of them maps to
the Devanagari code point with the same role. Urdu (Perso-Arabic) is folded with a phonetic table. Every non-ASCII
decimal digit becomes ASCII.

`fold` is LENGTH-PRESERVING (one code point in, one out), so spans found on folded text index the original text
exactly: detectors written for Devanagari and Latin work on eleven scripts without being rewritten, and the
sanitised output keeps its original script.

Standard library only, Python 3.9+.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Tuple

# ---------------------------------------------------------------- script blocks
BLOCKS: Dict[str, Tuple[int, int]] = {
    "deva": (0x0900, 0x097F), "beng": (0x0980, 0x09FF), "guru": (0x0A00, 0x0A7F), "gujr": (0x0A80, 0x0AFF),
    "orya": (0x0B00, 0x0B7F), "taml": (0x0B80, 0x0BFF), "telu": (0x0C00, 0x0C7F), "knda": (0x0C80, 0x0CFF),
    "mlym": (0x0D00, 0x0D7F), "arab": (0x0600, 0x06FF),
}
_BRAHMIC = ("beng", "guru", "gujr", "orya", "taml", "telu", "knda", "mlym")
SCRIPT_NAMES = {"latin": "Latin", "deva": "Devanagari (Hindi/Marathi)", "beng": "Bengali/Assamese", "guru": "Gurmukhi (Punjabi)",
                "gujr": "Gujarati", "orya": "Odia", "taml": "Tamil", "telu": "Telugu", "knda": "Kannada",
                "mlym": "Malayalam", "arab": "Perso-Arabic (Urdu)"}

# Code points whose offset twin in Devanagari is not the same letter (or would split a word).
_SPECIAL = {
    0x09CE: "त",    # Bengali khanda ta
    0x09F0: "र", 0x09F1: "व",             # Assamese ra, wa
    0x09FC: "व",
    0x0A70: "ं",    # Gurmukhi tippi (nasal)
    0x0A71: "ँ",    # Gurmukhi addak (gemination mark) -> harmless nasal-class sign inside the word
    0x0A72: "इ", 0x0A73: "उ", 0x0A74: "ॐ", 0x0A75: "्",
    0x0AF9: "\u095B",
    0x0B71: "व",    # Odia wa
    0x0BD7: "ौ",    # Tamil au length mark
    0x0B9A: "स",    # Tamil ca: read as "s" in names (Subramanian, Selvi, Saravanan)
    0x0D4E: "र",    # Malayalam dot reph
    0x0D7A: "ण", 0x0D7B: "न", 0x0D7C: "र", 0x0D7D: "ल", 0x0D7E: "ळ", 0x0D7F: "क",   # Malayalam chillus
    0x0D57: "ौ",
}

# Urdu / Arabic letters -> nearest Devanagari letter (context-free so per-character callers agree).
_ARABIC = {
    "ا": "ा", "آ": "आ", "أ": "अ", "إ": "इ", "ٱ": "ा", "ب": "ब", "پ": "प", "ت": "त", "ٹ": "ट", "ث": "स",
    "ج": "ज", "چ": "च", "ح": "ह", "خ": "\u0959", "د": "द", "ڈ": "ड", "ذ": "\u095B", "ر": "र", "ڑ": "\u095C", "ز": "\u095B",
    "ژ": "\u095B", "س": "स", "ش": "श", "ص": "स", "ض": "\u095B", "ط": "त", "ظ": "\u095B", "ع": "अ", "غ": "\u095A", "ف": "\u095E",
    "ق": "\u0958", "ک": "क", "ك": "क", "گ": "ग", "ل": "ल", "م": "म", "ن": "न", "ں": "ं", "و": "व", "ہ": "ह",
    "ه": "ह", "ھ": "ह", "ۂ": "ह", "ء": "अ", "ی": "ी", "ي": "ी", "ى": "ी", "ئ": "ई", "ے": "े", "ۓ": "े",
    "ۃ": "ा", "ة": "ा", "،": ",", "۔": ".", "؟": "?", "؛": ";", "٪": "%",
}
for _cp in list(range(0x064B, 0x0653)) + [0x0670]:   # short-vowel marks (zabar, zer, pesh, ...): keep inside the word
    _ARABIC[chr(_cp)] = "॑"

_FOLD: Dict[str, str] = {}
for _s in _BRAHMIC:
    lo, hi = BLOCKS[_s]
    for _cp in range(lo, hi + 1):
        ch = chr(_cp)
        d = unicodedata.decimal(ch, None)
        if d is not None:
            _FOLD[ch] = str(d)
        elif _cp in _SPECIAL:
            _FOLD[ch] = _SPECIAL[_cp]
        elif unicodedata.category(ch) != "Cn":
            _FOLD[ch] = chr(_cp - lo + 0x0900)
_FOLD.update(_ARABIC)
for _cp in list(range(0x0660, 0x066A)) + list(range(0x06F0, 0x06FA)) + list(range(0x0966, 0x0970)):
    _FOLD[chr(_cp)] = str(unicodedata.decimal(chr(_cp)))
assert all(len(v) == 1 for v in _FOLD.values()), "fold must stay length-preserving"
_FOLD_TABLE = str.maketrans(_FOLD)


_AR_LETTER = frozenset(k for k in _ARABIC if len(k) == 1 and unicodedata.category(k).startswith("L"))


def _arabic_context(src: str, out: str) -> str:
    """Urdu writes most short vowels implicitly: pick the Devanagari reading of alif/vav/ye from position."""
    o = list(out)
    n = len(src)
    for i, ch in enumerate(src):
        if ch not in "اٱویي":
            continue
        prev = src[i - 1] if i else ""
        nxt = src[i + 1] if i + 1 < n else ""
        initial = prev not in _AR_LETTER
        if ch in "اٱ":
            o[i] = "अ" if initial else "ा"
        elif ch == "و":
            if initial or nxt in "اٱ":
                o[i] = "व"
            elif nxt in _AR_LETTER:
                o[i] = "ू"
            else:
                o[i] = "ो"
        else:  # ye
            o[i] = "य" if (initial or nxt in "اٱو") else "ी"
    return "".join(o)


def fold(text: str) -> str:
    """Every Indian script onto Devanagari (and every digit onto ASCII), one code point for one."""
    if not text or text.isascii():
        return text
    out = text.translate(_FOLD_TABLE)
    if any("\u0600" <= c <= "\u06ff" for c in text):
        out = _arabic_context(text, out)
    return out


def script_of(ch: str) -> str:
    cp = ord(ch)
    if ch.isascii():
        return "latin" if ch.isalpha() else ""
    for name, (lo, hi) in BLOCKS.items():
        if lo <= cp <= hi:
            return name
    if 0x00C0 <= cp <= 0x024F:
        return "latin"
    return ""


def script_mix(text: str) -> Dict[str, int]:
    """Letter count per script, e.g. {'latin': 812, 'beng': 120}. Used for the report and routing."""
    out: Dict[str, int] = {}
    for ch in text:
        if ch.isalpha() or unicodedata.category(ch).startswith("M"):
            s = script_of(ch)
            if s:
                out[s] = out.get(s, 0) + 1
    return out


def has_foreign_script(text: str) -> bool:
    return any(s not in ("latin", "deva") for s in script_mix(text))


# ---------------------------------------------------------------- multilingual labels
# Written natively; folded at import, so the alias keys are exactly what the detectors see after `fold`.
# Each value is the Hindi label word the existing detectors already understand.
_NATIVE_LABELS = {
    "नाम": """নাম ਨਾਮ ਨਾਂ નામ ନାମ பெயர் పేరు ಹೆಸರು പേര് نام नाव""",
    "मरीज": """রোগী রোগীর ਮਰੀਜ਼ ਮਰੀਜ દર્દી ରୋଗୀ நோயாளி రోగి ರೋಗಿ രോഗി مریض रुग्ण""",
    "आयु": """বয়স ਉਮਰ ઉંમર ବୟସ வயது వయస్సు ವಯಸ್ಸು വയസ്സ് വയസ് عمر वय""",
    "लिंग": """লিঙ্গ ਲਿੰਗ લિંગ ଲିଙ୍ଗ பாலினம் లింగం ಲಿಂಗ ലിംഗം جنس""",
    "पिता": """পিতা পিতার বাবা ਪਿਤਾ પિતા ପିତା தந்தை తండ్రి ತಂದೆ അച്ഛൻ പിതാവ് والد ولد वडील""",
    "पति": """স্বামী স্বামীর ਪਤੀ પતિ ସ୍ୱାମୀ கணவர் கணவன் భర్త ಗಂಡ ಪತಿ ഭർത്താവ് شوہر पती""",
    "पत्नी": """স্ত্রী ਪਤਨੀ પત્ની ପତ୍ନୀ மனைவி భార్య ಹೆಂಡತಿ ಪತ್ನಿ ഭാര്യ بیوی زوجہ""",
    "माता": """মাতা মা ਮਾਤਾ માતા ମାତା தாய் తల్లి ತಾಯಿ അമ്മ والدہ आई""",
    "पुत्र": """পুত্র ছেলে ਪੁੱਤਰ પુત્ર ପୁଅ மகன் కుమారుడు ಮಗ മകൻ بیٹا मुलगा""",
    "पुत्री": """কন্যা মেয়ে ਧੀ પુત્રી ଝିଅ மகள் కుమార్తె ಮಗಳು മകൾ بیٹی मुलगी""",
    "पता": """ঠিকানা ਪਤਾ સરનામું ଠିକଣା முகவரி చిరునామా ವಿಳಾಸ വിലാസം پتہ पत्ता""",
    "ग्राम": """গ্রাম ਪਿੰਡ ગામ ଗ୍ରାମ கிராமம் గ్రామం ಗ್ರಾಮ ഗ്രാമം گاؤں گاؤن गाव""",
    "जिला": """জেলা ਜ਼ਿਲ੍ਹਾ ਜ਼ਿਲਾ જિલ્લો ଜିଲ୍ଲା மாவட்டம் జిల్లా ಜಿಲ್ಲೆ ജില്ല ضلع जिल्हा""",
    "मोबाइल": """মোবাইল ফোন ਮੋਬਾਈਲ ਫ਼ੋਨ ਫੋਨ મોબાઇલ ફોન ମୋବାଇଲ ଫୋନ கைபேசி தொலைபேசி మొబైల్ ఫోన్ ಮೊಬೈಲ್ ಫೋನ್
                 മൊബൈൽ ഫോൺ موبائل فون भ्रमणध्वनी""",
    "जन्म": """জন্ম ਜਨਮ જન્મ ଜନ୍ମ பிறந்த పుట్టిన ಜನ್ಮ ജനന پیدائش""",
}
_NATIVE_KIN = ("পিতা বাবা স্বামী স্ত্রী পুত্র কন্যা ਪਿਤਾ ਪਤੀ ਪਤਨੀ ਪੁੱਤਰ ਧੀ પિતા પતિ પત્ની પુત્ર પુત્રી ପିତା ସ୍ୱାମୀ ପତ୍ନୀ "
               "தந்தை கணவர் மனைவி மகன் மகள் తండ్రి భర్త భార్య కుమారుడు కుమార్తె ತಂದೆ ಗಂಡ ಪತ್ನಿ ಮಗ ಮಗಳು "
               "അച്ഛൻ ഭർത്താവ് ഭാര്യ മകൻ മകൾ والد ولد شوہر بیوی بیٹا بیٹی زوجہ वडील पती मुलगा मुलगी")
# honorifics after a name (garu, babu, sahib, begum, ...) and titles before one
_NATIVE_HON = "বাবু দিদি ਜੀ ਸਾਹਿਬ ਸਾਬ ભાઈ બેન ગારુ గారు அவர்கள் ಅವರು അവർകൾ صاحب جی بیگم"
_NATIVE_TITLE = "শ্রী শ্রীমতী ਸ਼੍ਰੀ ਸ੍ਰੀ ਸ਼੍ਰੀਮਤੀ શ્રી શ્રીમતી ଶ୍ରୀ ଶ୍ରୀମତୀ திரு திருமதி శ్రీ శ్రీమతి ಶ್ರೀ ಶ್ರೀಮತಿ ശ്രീ ശ്രീമതി جناب محترمہ"
_NATIVE_DOCTOR = "ডাঃ ডা. ডাক্তার ਡਾ. ਡਾਕਟਰ ડૉ. ડો. ડોક્ટર ଡାକ୍ତର டாக்டர் மருத்துவர் డాక్టర్ ವೈದ್ಯ ಡಾ. ഡോ. ഡോക്ടർ ڈاکٹر ڈاکٹر"


def _folded_words(s: str) -> List[str]:
    return [fold(unicodedata.normalize("NFC", w)) for w in s.split()]


LABEL_ALIAS: Dict[str, str] = {}
for _canon, _words in _NATIVE_LABELS.items():
    for _w in _folded_words(_words):
        if _w != _canon:
            LABEL_ALIAS.setdefault(_w, _canon)
# possessive particles between a kinship word and "name" (Punjabi da/di/de, Hindi/Urdu ka/ki/ke)
POSSESSIVES: Tuple[str, ...] = tuple(sorted(set(_folded_words("ਦਾ ਦੀ ਦੇ کا کی کے")) | {"का", "की", "के"}, key=len, reverse=True))
AGE_WORDS: Tuple[str, ...] = tuple(sorted({w for w, c in LABEL_ALIAS.items() if c == "आयु"}, key=len, reverse=True))
LABEL_WORDS: FrozenSet[str] = frozenset(LABEL_ALIAS) | frozenset(POSSESSIVES)
KIN_WORDS: Tuple[str, ...] = tuple(sorted(set(_folded_words(_NATIVE_KIN)), key=len, reverse=True))
HONORIFICS: FrozenSet[str] = frozenset(_folded_words(_NATIVE_HON))
TITLES: FrozenSet[str] = frozenset(_folded_words(_NATIVE_TITLE))
DOCTOR_PREFIXES: Tuple[str, ...] = tuple(sorted({w.rstrip(".") for w in _folded_words(_NATIVE_DOCTOR)}, key=len, reverse=True))


def alias_label_word(w: str) -> str:
    """A folded label word in any supported language -> the Hindi label word the detectors know."""
    return LABEL_ALIAS.get(w, w)


@lru_cache(maxsize=65536)
def fold_word(w: str) -> str:
    return fold(unicodedata.normalize("NFC", w))


def supported_scripts() -> List[str]:
    return [SCRIPT_NAMES[k] for k in ("latin", "deva", "beng", "guru", "gujr", "orya", "taml", "telu", "knda", "mlym", "arab")]


def iter_spans_text(text: str, spans: Iterable[Tuple[int, int]]) -> List[str]:
    """Original-script surfaces for spans computed on fold(text) (identity because fold keeps length)."""
    return [text[s:e] for s, e in spans]
