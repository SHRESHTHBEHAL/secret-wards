# STUB: replaced by the real module
"""Identity-fact harvesting (stub). Emits one Record per locator with empty Facts."""
from __future__ import annotations

from typing import List

from .types import KIND_CSV, KIND_JSON, Facts, ParsedFile, Record


def _ptr(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def record_locs(pf: ParsedFile) -> List[str]:
    if pf.kind == KIND_CSV:
        return ["row:%d" % i for i in range(len(pf.rows))]
    if pf.kind == KIND_JSON and isinstance(pf.data, dict):
        locs = []
        for k, v in pf.data.items():
            if isinstance(v, list):
                locs.extend("/%s/%d" % (_ptr(str(k)), i) for i in range(len(v)))
        if locs:
            return locs
    return ["doc"]


def harvest_file(pf: ParsedFile) -> List[Record]:
    return [Record(rel=pf.rel, loc=loc, facts=Facts()) for loc in record_locs(pf)]
