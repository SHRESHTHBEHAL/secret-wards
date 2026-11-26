"""Orchestration: load -> harvest -> link -> pseudonymise -> sanitize -> leak gate -> export.

Outputs no data, no file names and no key material. stderr only ever carries an exception class name
and a stage name. Standard library only, Python 3.9+.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import detect as _detect_mod
from . import gate
from . import harvest as _harvest_mod
from .harvest import harvest_file
from .ingest import R_INTERNAL, R_UNSUPPORTED, dump_json, escapes_root, is_ndjson, link_marker_sha, load, walk
from .link import link
from .normalize import digits_only, to_ascii_digits
from .pseudo import Keys, ShiftBook
from .report import (
    build_report, file_entry, record_line, records_text, report_text, sort_records,
)
from .sanitize import DobWatch, Env, Sanitized, sanitize_file
from .types import KIND_CSV, KIND_FHIR, KIND_JSON, KIND_QUARANTINE, ParsedFile, Record

R_LEAK = "leak_gate"
PLACEHOLDER = "[REDACTED]"
_ROW_LOC = re.compile(r"^row:\d+$")
_DIGIT_RUN5 = re.compile(r"[0-9]{5,}")


class _Errors:
    """Writes `raksha: <ExceptionClass> in <stage>` once per pair. Never data."""

    def __init__(self) -> None:
        self.seen = set()  # type: Set[Tuple[str, str]]

    def __call__(self, stage: str, exc: BaseException) -> None:
        key = (type(exc).__name__, stage)
        if key in self.seen:
            return
        self.seen.add(key)
        try:
            sys.stderr.write("raksha: %s in %s\n" % key)
        except Exception:  # noqa: BLE001
            pass


@dataclasses.dataclass
class _Item:
    rel: str
    pf: ParsedFile
    records: List[Record] = dataclasses.field(default_factory=list)
    reason: str = ""                 # quarantine reason; "" while still alive
    result: Optional[Sanitized] = None
    out_rel: str = ""
    written: bool = False


# ----------------------------------------------------------------------------- helpers

def _sha_of(path: Path) -> str:
    try:
        with open(str(path), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def _quarantine(it: _Item, reason: str) -> None:
    if not it.reason:
        it.reason = reason
    it.result = None


def _safe_rel(rel: str) -> bool:
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return False
    return all(p not in ("", ".", "..") for p in rel.split("/"))


def _leaves(v: Any, out: List[str]) -> None:
    stack = [v]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            for k, y in x.items():
                out.append(str(k))
                stack.append(y)
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, str):
            out.append(x)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append(repr(x))


# FHIR / JSON reference-like keys: a leak inside one becomes a keyed token (same value, same token), so an
# id and every reference to it stay equal and keep the id syntax ([A-Za-z0-9.-])
_REF_KEYS = frozenset({"id", "fullUrl", "reference"})
_REF_SHAPE = re.compile(r"^[A-Za-z0-9\-.:/_#|]+$")


def _clean_json(v: Any, fb: gate.Forbidden, tok: Optional[Any] = None, key: str = "") -> Any:
    if isinstance(v, str):
        if tok is not None and key in _REF_KEYS and _REF_SHAPE.match(v):
            return gate.clean(v, fb, tok)[0]
        return gate.clean(v, fb, PLACEHOLDER)[0]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        if gate.scan(repr(v), fb):
            return 0 if isinstance(v, int) else 0.0
        return v
    if isinstance(v, list):
        return [_clean_json(x, fb, tok, key) for x in v]
    if isinstance(v, dict):
        out = {}  # type: Dict[str, Any]
        for k, x in v.items():
            nk = gate.clean(str(k), fb, PLACEHOLDER)[0]
            base, n = nk, 2
            while nk in out:
                nk = "%s_%d" % (base, n)
                n += 1
            out[nk] = _clean_json(x, fb, tok, str(k))
        return out
    return v


def _csv_shape(text: str, delim: str) -> List[int]:
    return [len(r) for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim, strict=False)]


def gate_content(content: str, kind: str, delim: str, fb: gate.Forbidden,
                 tok: Optional[Any] = None) -> Tuple[Optional[str], int]:
    """Leak-gate one output text. Returns (clean text or None when it must be quarantined, hits).
    `tok` (leaked surface -> keyed token) keeps FHIR ids and references consistent when one holds a leak."""
    hits = 0
    if kind in (KIND_JSON, KIND_FHIR):
        try:
            data = json.loads(content)
        except ValueError:
            return None, 0
        flat = []  # type: List[str]
        _leaves(data, flat)
        h_flat = gate.scan("\n".join(flat), fb)
        if not h_flat and not gate.scan(content, fb):
            return content, 0
        hits += len(h_flat)
        if h_flat:
            content = dump_json(_clean_json(data, fb, tok))
        content, n = gate.clean(content, fb, PLACEHOLDER, keep='"{}[]:,\n')
        hits += n
        try:
            data = json.loads(content)
        except ValueError:
            return None, hits
        flat = []
        _leaves(data, flat)
        if gate.scan(content, fb) or gate.scan("\n".join(flat), fb):
            return None, hits
        return content, hits
    if not gate.scan(content, fb):
        return content, 0
    if kind == KIND_CSV:
        shape = _csv_shape(content, delim)
        content, n = gate.clean(content, fb, PLACEHOLDER, keep=delim + '"\r\n')
        hits += n
        if _csv_shape(content, delim) != shape:
            return None, hits
    else:
        content, n = gate.clean(content, fb, PLACEHOLDER)
        hits += n
    if gate.scan(content, fb):
        return None, hits
    return content, hits


def _write_text(root: Path, rel: str, content: str) -> None:
    dest = root / rel
    real_root = os.path.realpath(str(root))
    dest.parent.mkdir(parents=True, exist_ok=True)
    real_parent = os.path.realpath(str(dest.parent))
    if real_parent != real_root and not real_parent.startswith(real_root + os.sep):
        raise PermissionError("outside output")
    if os.path.islink(str(dest)):
        raise PermissionError("symlink")
    with open(str(dest), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


# ----------------------------------------------------------------------------- run

def run(input_dir: Path, output_dir: Path, secret: bytes, policy: Dict[str, Any]) -> int:
    # run-wide caches and cross-file typing state never outlive one run
    _detect_mod.reset_caches()
    _harvest_mod.reset()
    try:
        return _run(input_dir, output_dir, secret, policy)
    finally:
        _detect_mod.reset_caches()
        _harvest_mod.reset()


def _run(input_dir: Path, output_dir: Path, secret: bytes, policy: Dict[str, Any]) -> int:
    t0 = time.monotonic()
    if not secret:
        sys.stderr.write("raksha: key not configured; nothing processed\n")
        return 2
    err = _Errors()
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    real_in = os.path.realpath(str(input_dir))
    real_out = os.path.realpath(str(output_dir))
    if real_out == real_in or real_out.startswith(real_in + os.sep):
        sys.stderr.write("raksha: output directory must be outside the input directory\n")
        return 2
    keys = Keys(secret)
    policy = dict(policy or {})

    # 1. load (identical bytes parsed once)
    items = []  # type: List[_Item]
    by_sha = {}  # type: Dict[str, ParsedFile]
    for path in walk(input_dir):
        rel = path.relative_to(input_dir).as_posix()
        if escapes_root(path, input_dir):  # never opened: quarantined under a stand-in digest
            items.append(_Item(rel=rel, pf=ParsedFile(rel=rel, sha256=link_marker_sha(path), kind=KIND_QUARANTINE,
                                                      reason=R_UNSUPPORTED), reason=R_UNSUPPORTED))
            continue
        sha = _sha_of(path)
        if sha and sha in by_sha:
            pf = dataclasses.replace(by_sha[sha], rel=rel)
        else:
            pf = load(path, input_dir)
            if not pf.sha256:
                pf = dataclasses.replace(pf, sha256=sha)
            if sha:
                by_sha[sha] = pf
        it = _Item(rel=rel, pf=pf)
        if pf.kind == KIND_QUARANTINE:
            it.reason = pf.reason or R_INTERNAL
        items.append(it)

    # 2. harvest (once per content, cloned per path)
    harvested = {}  # type: Dict[str, Optional[List[Record]]]
    first = {}  # type: Dict[str, List[Record]]
    try:  # cross-file id-column typing; files it leaves untouched keep their first-pass records
        uniq = {}  # type: Dict[str, ParsedFile]
        for it in items:
            if not it.reason and it.pf.sha256 not in uniq:
                uniq[it.pf.sha256] = dataclasses.replace(it.pf, rel=it.rel)
        first = _harvest_mod.prepare([uniq[k] for k in sorted(uniq)]) or {}
    except Exception as exc:  # noqa: BLE001
        err("harvest", exc)
        _harvest_mod.reset()
        first = {}
    for it in items:
        if it.reason:
            continue
        sha = it.pf.sha256
        if (sha not in harvested and sha in first and harvest_file is _harvest_mod.harvest_file
                and not _harvest_mod.has_override(it.pf)):
            harvested[sha] = first[sha]
        if sha not in harvested:
            try:
                harvested[sha] = list(harvest_file(dataclasses.replace(it.pf, rel=it.rel)))
            except Exception as exc:  # noqa: BLE001
                err("harvest", exc)
                harvested[sha] = None
        recs = harvested[sha]
        if recs is None:
            _quarantine(it, R_INTERNAL)
            continue
        it.records = [Record(rel=it.rel, loc=r.loc, facts=r.facts) for r in recs]

    all_records = [r for it in items if not it.reason for r in it.records]

    # 3. link
    try:
        assign, book = link(all_records)
    except Exception as exc:  # noqa: BLE001 - fall back to linking nothing
        err("link", exc)
        assign, book = {(r.rel, r.loc): None for r in all_records}, {}

    # 4. pseudonyms
    forbidden_digits = set()
    for k in sorted(book):
        for f in book[k].facts:
            for v in list(f.raw_ids or []) + list(f.ids or []):
                d = digits_only(str(v))
                forbidden_digits.update(_DIGIT_RUN5.findall(to_ascii_digits(str(v))))
                if len(d) >= 5:
                    forbidden_digits.add(d)
    fd = sorted(f for f in forbidden_digits if len(f) <= 12)
    fset = frozenset(fd)
    pseudonyms = {}  # type: Dict[str, str]
    for k in sorted(book):
        p = keys.pseudonym(k)
        if _has_forbidden(p[4:], fset):  # rare: let Keys pick the next safe candidate
            p = keys.pseudonym(k, forbidden_digits=fd)
        pseudonyms[k] = p

    try:
        fb = gate.forbidden_from_facts(
            [r.facts for r in all_records] + [f for k in sorted(book) for f in book[k].facts])
    except Exception as exc:  # noqa: BLE001 - without a gate nothing may leave
        err("gate", exc)
        fb = None

    try:   # every patient on its own date-shift offset (defeats global-shift recovery)
        shifts = ShiftBook(keys, list(book), int(policy.get("date_shift_max_days", 180)),
                           int(policy.get("date_shift_min_days", 30)))
    except Exception as exc:  # noqa: BLE001 - fall back to independent keyed offsets
        err("shifts", exc)
        shifts = None
    env = Env(keys=keys, assign=assign, book=book, policy=policy, pseudonyms=pseudonyms,
              records={it.rel: it.records for it in items if not it.reason},
              shifts=shifts)

    # 5-6. sanitize + leak gate
    def _san(it: _Item) -> int:
        hits = 0
        if fb is None:
            _quarantine(it, R_INTERNAL)
            return 0
        try:
            res = sanitize_file(it.pf, env)
        except Exception as exc:  # noqa: BLE001
            err("sanitize", exc)
            _quarantine(it, R_INTERNAL)
            return 0
        try:
            content, n = gate_content(res.content, it.pf.kind, it.pf.delimiter or ",", fb,
                                      tok=lambda seg: "x" + keys.opaque("ref|" + seg, 10).lower())
            hits += n
            if content is not None and is_ndjson(it.pf):
                # JSON Lines in, JSON Lines out: one value per line, gated again as written
                content = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in json.loads(content))
                if gate.scan(content, fb):
                    content = None
            out_rel = res.out_rel
            if gate.scan(out_rel, fb):
                out_rel, n = gate.clean(out_rel, fb, keys.opaque(it.pf.sha256 or it.rel), keep="/.")
                hits += n
                if gate.scan(out_rel, fb):
                    content = None
        except Exception as exc:  # noqa: BLE001
            err("gate", exc)
            _quarantine(it, R_INTERNAL)
            return 0
        if content is None:
            _quarantine(it, R_LEAK)
            return 0
        if not _safe_rel(out_rel):
            _quarantine(it, R_INTERNAL)
            return 0
        it.result = dataclasses.replace(res, content=content)
        it.out_rel = out_rel
        return hits

    try:
        env.dob_watch = DobWatch([r.facts.dob for r in all_records])
    except Exception as exc:  # noqa: BLE001
        err("shifts", exc)
    item_hits = {}  # type: Dict[int, int]
    for i, it in enumerate(items):
        if not it.reason:
            item_hits[i] = _san(it)
    # a shifted date that equals someone's DOB reads as a DOB leak: move that key a day on, redo its files
    w = env.dob_watch
    for _ in range(8):
        if w is None or not w.hit or shifts is None:
            break
        hit = sorted(w.hit)
        w.hit = set()
        redo_rel, redo_sha = set(), set()  # type: Set[str], Set[str]
        for k in hit:
            shifts.bump(k)
            if k in book:
                redo_rel.update(rel for rel, _loc in book[k].records)
            elif k.startswith("rec:"):
                redo_sha.add(k.split(":", 2)[1])
        for i, it in enumerate(items):
            if not it.reason and it.result is not None and (it.rel in redo_rel or it.pf.sha256 in redo_sha):
                it.result = None
                item_hits[i] = _san(it)
    gate_hits = sum(item_hits[i] for i in sorted(item_hits))

    # 7. resolve output path collisions (case-insensitive file systems included)
    used = set()  # type: Set[str]
    for it in items:
        if it.result is None:
            continue
        rel = it.out_rel
        if rel.casefold() in used:
            stem, ext = posixpath.splitext(rel)
            tag = it.pf.sha256 or it.rel
            rel = "%s_%s%s" % (stem, keys.opaque(tag), ext)
            n = 1
            while rel.casefold() in used:
                rel = "%s_%s%s" % (stem, keys.opaque("%s|%d" % (tag, n)), ext)
                n += 1
        used.add(rel.casefold())
        it.out_rel = rel

    san_root = output_dir / "sanitized"
    ok = True
    try:
        san_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        err("write", exc)
        ok = False
    for it in items:
        if it.result is None or not ok:
            if it.result is not None:
                _quarantine(it, R_INTERNAL)
            continue
        try:
            _write_text(san_root, it.out_rel, it.result.content)
            it.written = True
        except Exception as exc:  # noqa: BLE001
            err("write", exc)
            try:
                p = san_root / it.out_rel
                if p.is_file() and not p.is_symlink():
                    p.unlink()
            except Exception:  # noqa: BLE001
                pass
            _quarantine(it, R_INTERNAL)

    # records.jsonl (gated)
    lines = []  # type: List[Dict[str, Any]]
    entities = {}  # type: Dict[str, int]
    identifiers = 0
    for it in items:
        if not it.written or it.result is None:
            continue
        for k in sorted(it.result.counts):
            v = it.result.counts[k]
            if k == "identifiers":
                identifiers += int(v)
            elif k.isupper():
                entities[k] = entities.get(k, 0) + int(v)
        ndj = is_ndjson(it.pf)
        for loc, psn, status in it.result.records:
            loc = str(loc)
            if ndj:   # JSON Lines: line N of data is record row:N
                m = re.match(r"^/([0-9]+)$", loc)
                if m:
                    loc = "row:%s" % m.group(1)
            if not _ROW_LOC.match(loc) and fb is not None and gate.scan(loc, fb):
                loc, n = gate.clean(loc, fb, "REDACTED", keep="/")
                gate_hits += n
            lines.append(record_line("sanitized/" + it.out_rel, loc, psn, status or "sanitized"))
    lines = sort_records(lines)

    rec_ok = True
    try:
        _write_root(output_dir, "records.jsonl", records_text(lines))
    except Exception as exc:  # noqa: BLE001
        err("records", exc)
        rec_ok = False

    files = []  # type: List[Dict[str, Any]]
    records_quarantined = 0
    for it in items:
        if it.written:
            files.append(file_entry(it.pf.sha256, "sanitized/" + it.out_rel))
        else:
            files.append(file_entry(it.pf.sha256, None, it.reason or R_INTERNAL))
            records_quarantined += len(it.records)
    n_san = sum(1 for f in files if f["status"] == "sanitized")
    counts = {
        "files_total": len(files),
        "files_sanitized": n_san,
        "files_quarantined": len(files) - n_san,
        "records_processed": len(lines),
        "identifiers_detected": identifiers,
        "records_linked": sum(1 for r in lines if r["patient"] is not None),
        "records_generalized": sum(1 for r in lines if r["status"] == "generalized"),
        "records_suppressed": sum(1 for r in lines if r["status"] == "suppressed"),
        "records_quarantined": records_quarantined,
        "leak_gate_hits": gate_hits,
    }
    report = build_report(files, counts, entities, time.monotonic() - t0)
    if fb is not None:
        gate_hits += _gate_report(report, fb)
        report["counts"]["leak_gate_hits"] = gate_hits
    text = report_text(report)
    rep_ok = True
    try:
        _write_root(output_dir, "report.json", text)
    except Exception as exc:  # noqa: BLE001
        err("report", exc)
        rep_ok = False

    print("files %d sanitized %d quarantined %d records %d linked %d" % (
        counts["files_total"], counts["files_sanitized"], counts["files_quarantined"],
        counts["records_processed"], counts["records_linked"]))
    return 0 if (ok and rec_ok and rep_ok and len(files) == len(items)) else 1


def _gate_report(report: Dict[str, Any], fb: gate.Forbidden) -> int:
    """Gate report.json field by field. Hashes (input_sha256), counts, timing and resources are never
    touched: they are not personal data, and altering a hash would break the file mapping."""
    hits = 0
    for f in report.get("files") or []:
        for key, keep in (("output", "/."), ("reason", "_")):
            v = f.get(key)
            if isinstance(v, str) and gate.scan(v, fb):
                f[key], n = gate.clean(v, fb, "REDACTED", keep=keep)
                hits += n
    ents = report.get("entities") or {}
    if any(gate.scan(str(k), fb) for k in ents):
        report["entities"] = {}
    return hits


def _has_forbidden(body: str, fset: frozenset) -> bool:
    """Same test as Keys.pseudonym, via set lookups of every substring of length 5+."""
    digits = "".join(c for c in body if c.isdigit())
    for t in (body, digits):
        for i in range(len(t)):
            for j in range(i + 5, len(t) + 1):
                if t[i:j] in fset:
                    return True
    return False


def _write_root(output_dir: Path, name: str, content: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    p = output_dir / name
    if os.path.islink(str(p)):
        raise PermissionError("symlink")
    with open(str(p), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def emergency_report(input_dir: Path, output_dir: Path) -> int:
    """Last-resort export: every input file listed as quarantined (internal_error). Returns 1."""
    try:
        output_dir = Path(output_dir)
        (output_dir / "sanitized").mkdir(parents=True, exist_ok=True)
        files = []
        try:
            paths = walk(Path(input_dir))
        except Exception:  # noqa: BLE001
            paths = []
        for p in paths:
            unsafe = escapes_root(p, Path(input_dir))
            files.append(file_entry(link_marker_sha(p) if unsafe else _sha_of(p), None, R_INTERNAL))
        counts = {k: 0 for k in ("files_total", "files_sanitized", "files_quarantined", "records_processed",
                                 "identifiers_detected", "records_linked", "records_generalized",
                                 "records_suppressed", "records_quarantined")}
        counts["files_total"] = counts["files_quarantined"] = len(files)
        _write_root(output_dir, "records.jsonl", "")
        _write_root(output_dir, "report.json", report_text(build_report(files, counts, {}, 0.0)))
    except Exception:  # noqa: BLE001
        pass
    return 1
