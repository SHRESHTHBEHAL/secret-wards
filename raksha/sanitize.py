# STUB: replaced by the real module
"""Record scrubbing (stub). Redacts everything; never passes data through."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .harvest import record_locs
from .ingest import dump_csv, dump_json
from .pseudo import Keys
from .types import KIND_CSV, KIND_FHIR, KIND_JSON, ParsedFile, Patient

R = "[REDACTED]"


@dataclass
class Env:
    keys: Keys
    assign: Dict[Tuple[str, str], Optional[str]]
    book: Dict[str, Patient]
    policy: Dict[str, Any]
    pseudonyms: Dict[str, str] = field(default_factory=dict)


@dataclass
class Sanitized:
    out_rel: str
    content: str
    records: List[Tuple[str, Optional[str], str]]
    counts: Dict[str, int]


def _redact(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, str):
        return R
    if isinstance(v, (int, float)):
        return 0
    if isinstance(v, list):
        return [_redact(x) for x in v]
    if isinstance(v, dict):
        return {k: _redact(x) for k, x in v.items()}
    return R


def sanitize_file(pf: ParsedFile, env: Env) -> Sanitized:
    if pf.kind == KIND_CSV:
        copy = ParsedFile(rel=pf.rel, sha256=pf.sha256, kind=pf.kind, delimiter=pf.delimiter,
                          header=list(pf.header), rows=[[R for _ in row] for row in pf.rows])
        content = dump_csv(copy)
    elif pf.kind in (KIND_JSON, KIND_FHIR):
        content = dump_json(_redact(pf.data))
    else:
        content = "\n".join(R if line.strip() else "" for line in pf.text.splitlines()) + "\n"
    recs = [(loc, None, "sanitized") for loc in record_locs(pf)]
    return Sanitized(out_rel=pf.rel, content=content, records=recs, counts={"identifiers": 0})
