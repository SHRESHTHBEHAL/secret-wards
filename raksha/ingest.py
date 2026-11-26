"""Read every input file and turn it into a ParsedFile, or quarantine it.

Never raises from `load`. Format is decided from content; the extension is a hint only.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .types import (
    KIND_CSV,
    KIND_FHIR,
    KIND_JSON,
    KIND_QUARANTINE,
    KIND_TEXT,
    ParsedFile,
)

MAX_JSON_DEPTH = 200

R_EMPTY = "empty_file"
R_UNSUPPORTED = "unsupported_format"
R_ENCODING = "invalid_encoding"
R_JSON = "malformed_json"
R_DEEP = "too_deep"
R_CSV = "malformed_csv"
R_INTERNAL = "internal_error"

_BINARY_MAGIC = (
    b"%PDF",
    b"\xff\xd8\xff",          # JPEG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a",
    b"GIF89a",
    b"PK\x03\x04",            # ZIP / docx / xlsx
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",              # gzip
    b"BM",                    # bitmap (checked only with more evidence below)
)

# Bytes that cp1252 leaves undefined.
_CP1252_UNDEFINED = frozenset((0x81, 0x8D, 0x8F, 0x90, 0x9D))
_CSV_DELIMS = (",", "\t", ";", "|")

# Attachments and long notes routinely exceed the csv module's 128 KB field default.
csv.field_size_limit(2 ** 31 - 1)


def walk(input_dir: Path) -> List[Path]:
    """Every regular file under input_dir (hidden ones included), sorted by posix relative path."""
    root = Path(input_dir)
    found: List[Tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            found.append((p.relative_to(root).as_posix(), p))
    found.sort(key=lambda t: t[0])
    return [p for _, p in found]


def escapes_root(path: Path, input_dir: Path) -> bool:
    """True when `path` is a symlink (at any level below input_dir) whose target lies outside input_dir,
    or cannot be resolved. Such files are never opened: they are listed as quarantined."""
    try:
        if not _any_link_below(Path(path), Path(input_dir)):
            return False
        root = os.path.realpath(str(input_dir))
        real = os.path.realpath(str(path))
        return not (real.startswith(root + os.sep) and os.path.isfile(real))
    except (OSError, ValueError):
        return True


def _any_link_below(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    cur = root
    for part in rel.parts:
        cur = cur / part
        if os.path.islink(str(cur)):
            return True
    return False


def link_marker_sha(path: Path) -> str:
    """Stable stand-in digest for a symlink that points outside the input (its target is never read)."""
    try:
        target = os.readlink(str(path))
    except OSError:
        target = ""
    return hashlib.sha256(b"raksha-unfollowed-symlink\0" + os.fsencode(target)).hexdigest()


def _rel(path: Path, input_dir: Path) -> str:
    try:
        return Path(path).relative_to(Path(input_dir)).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _quarantine(rel: str, sha: str, reason: str) -> ParsedFile:
    return ParsedFile(rel=rel, sha256=sha, kind=KIND_QUARANTINE, reason=reason)


def _is_binary_magic(raw: bytes) -> bool:
    for magic in _BINARY_MAGIC:
        if magic == b"BM":
            continue
        if raw.startswith(magic):
            return True
    return False


def _looks_utf16(raw: bytes) -> Optional[str]:
    """Codec name when raw is UTF-16 (BOM, or a high share of NUL bytes), else None."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    sample = raw[:4096]
    if len(sample) < 4:
        return None
    nuls = sample.count(0)
    if nuls / len(sample) < 0.3:
        return _utf16_indic(sample)
    even = sample[0::2].count(0)
    odd = sample[1::2].count(0)
    return "utf-16-be" if even > odd else "utf-16-le"


def _utf16_indic(sample: bytes) -> Optional[str]:
    """BOM-less UTF-16 of Indic text has no NULs: every high byte is the script block (0x09-0x0D).
    Accept it only when one byte lane is almost all block bytes and the text decodes to letters."""
    if len(sample) < 8:
        return None
    for codec, lane in (("utf-16-le", sample[1::2]), ("utf-16-be", sample[0::2])):
        block = sum(1 for b in lane if b in (0x00, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x06))
        if block / len(lane) < 0.9 or sum(1 for b in lane if b != 0) / len(lane) < 0.3:
            continue
        try:
            text = sample[: len(sample) // 2 * 2].decode(codec)
        except UnicodeDecodeError:
            continue
        letters = sum(1 for c in text if c.isalpha() or c.isspace() or c.isdigit() or "\u0900" <= c <= "\u0dff")
        if letters / max(1, len(text)) > 0.85:
            return codec
    return None


def _cp1252_plausible(raw: bytes) -> bool:
    """Legacy single-byte text: no undefined cp1252 bytes, no 0xFE/0xFF, no stray UTF-8 lead/continuation pairs,
    no C0 controls other than tab/newline/CR/form feed."""
    for b in raw:
        if b in _CP1252_UNDEFINED or b in (0xFE, 0xFF):
            return False
        if b < 0x20 and b not in (0x09, 0x0A, 0x0D, 0x0C):
            return False
    # A UTF-8 lead byte (0xC2-0xF4) followed by a continuation byte (0x80-0xBF) means broken UTF-8, not cp1252.
    for i in range(len(raw) - 1):
        if 0xC2 <= raw[i] <= 0xF4 and 0x80 <= raw[i + 1] <= 0xBF:
            return False
    # Mostly-ASCII text with only a sparse sprinkling of high bytes.
    high = sum(1 for b in raw if b >= 0x80)
    return high * 10 <= len(raw)


def _decode(raw: bytes) -> Optional[str]:
    """PRD R1.3 decoding order. None when nothing decodes cleanly."""
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    codec = _looks_utf16(raw)
    if codec is not None:
        try:
            text = raw.decode(codec)
        except UnicodeDecodeError:
            return None
        return text[1:] if text.startswith("﻿") else text
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if not _cp1252_plausible(raw):
        return None
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError:
        return None
    if any("\x80" <= ch <= "\x9f" for ch in text):
        return None
    return text


def _json_depth_exceeds(text: str, limit: int = MAX_JSON_DEPTH) -> bool:
    """Iterative bracket depth count outside strings."""
    depth = 0
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{" or ch == "[":
            depth += 1
            if depth > limit:
                return True
        elif ch == "}" or ch == "]":
            if depth > 0:
                depth -= 1
    return False


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _count_outside_quotes(line: str, ch: str) -> int:
    n = 0
    in_q = False
    for c in line:
        if c == '"':
            in_q = not in_q
        elif c == ch and not in_q:
            n += 1
    return n


def _sniff_delimiter(header_line: str, ext: str) -> str:
    counts = {d: _count_outside_quotes(header_line, d) for d in _CSV_DELIMS}
    if ext == ".tsv" and counts["\t"] > 0:
        return "\t"
    best = ","
    best_n = 0
    for d in _CSV_DELIMS:  # fixed order breaks ties deterministically
        if counts[d] > best_n:
            best, best_n = d, counts[d]
    return best


def _parse_csv(text: str, delimiter: str) -> List[List[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False)
    # Keep blank lines as empty rows so row:N locators match the input line for line.
    return [row for row in reader]


def _load_json(rel: str, sha: str, text: str) -> ParsedFile:
    if _json_depth_exceeds(text):
        return _quarantine(rel, sha, R_DEEP)
    try:
        # NaN / Infinity are not JSON: keep them as text so the export stays valid JSON
        data = json.loads(text, strict=False, parse_constant=lambda c: c)
    except (ValueError, RecursionError):
        return _quarantine(rel, sha, R_JSON)
    kind = KIND_FHIR if isinstance(data, dict) and data.get("resourceType") == "Bundle" else KIND_JSON
    return ParsedFile(rel=rel, sha256=sha, kind=kind, text=text, data=data)


def _load_inner(path: Path, rel: str, sha: str, raw: bytes) -> ParsedFile:
    if not raw.strip():
        return _quarantine(rel, sha, R_EMPTY)
    if _is_binary_magic(raw):
        return _quarantine(rel, sha, R_UNSUPPORTED)
    text = _decode(raw)
    if text is None:
        return _quarantine(rel, sha, R_ENCODING)
    if "\x00" in text:
        return _quarantine(rel, sha, R_UNSUPPORTED)
    stripped = text.lstrip()
    if not stripped:
        return _quarantine(rel, sha, R_EMPTY)
    ext = path.suffix.lower()
    head = stripped[:1]
    if head in ("{", "["):
        pf = _load_json(rel, sha, text)
        # A .json file (or a too-deep payload) stays quarantined. Other files that merely start with a bracket
        # but are not JSON (for example "[30/05/26, 9:32 pm] ..." chat exports) fall through to text / CSV.
        if pf.kind != KIND_QUARANTINE or ext == ".json" or pf.reason != R_JSON:
            return pf
    elif ext == ".json":
        return _quarantine(rel, sha, R_JSON)
    if head == "<" and (stripped.startswith("<?xml") or stripped[1:2].isalpha() or stripped[1:2] == "!"):
        return _quarantine(rel, sha, R_UNSUPPORTED)
    if re.match(r"(?:MSH|FHS|BHS)\|", stripped):
        return _quarantine(rel, sha, R_UNSUPPORTED)    # HL7 v2 messages: a format we do not parse safely
    if ext in (".csv", ".tsv"):
        header_line = _first_line(text)
        if not header_line:
            return _quarantine(rel, sha, R_EMPTY)
        delim = _sniff_delimiter(header_line, ext)
        try:
            rows = _parse_csv(text, delim)
        except csv.Error:
            return _quarantine(rel, sha, R_CSV)
        while rows and not any(c.strip() for c in rows[0]):
            rows.pop(0)   # blank lines above the header are not data rows
        if not rows:
            return _quarantine(rel, sha, R_EMPTY)
        return ParsedFile(rel=rel, sha256=sha, kind=KIND_CSV, text=text, delimiter=delim,
                          header=list(rows[0]), rows=[list(r) for r in rows[1:]])
    return ParsedFile(rel=rel, sha256=sha, kind=KIND_TEXT, text=text)


def load(path: Path, input_dir: Path) -> ParsedFile:
    """Parse one file. Never raises; any failure becomes a quarantine with a reason code."""
    rel = ""
    sha = ""
    try:
        path = Path(path)
        rel = _rel(path, input_dir)
        with open(str(path), "rb") as fh:
            raw = fh.read()
        sha = hashlib.sha256(raw).hexdigest()
        return _load_inner(path, rel, sha, raw)
    except Exception:  # noqa: BLE001 - the contract is never raise
        try:
            return _quarantine(rel, sha, R_INTERNAL)
        except Exception:  # pragma: no cover
            return ParsedFile(rel="", sha256="", kind=KIND_QUARANTINE, reason=R_INTERNAL)


def dump_csv(pf: ParsedFile) -> str:
    """Serialise header + rows with the file's own delimiter."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=pf.delimiter or ",", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(pf.header)
    for row in pf.rows:
        writer.writerow(row)
    return buf.getvalue()


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
