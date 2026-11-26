"""report.json and records.jsonl builders (SPEC sections 5 and 6). Standard library only, Python 3.9+."""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "raksha-report/1"
COUNT_KEYS = (
    "files_total", "files_sanitized", "files_quarantined", "records_processed",
    "identifiers_detected", "records_linked", "records_generalized", "records_suppressed",
    "records_quarantined",
)

_ROW = re.compile(r"^row:(\d+)$")


def loc_key(loc: str) -> Tuple[Any, ...]:
    """Natural order: row numbers numerically, then JSON pointers part by part (numbers numerically), then doc."""
    m = _ROW.match(loc)
    if m:
        return (0, int(m.group(1)), ())
    if loc.startswith("/"):
        parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in loc[1:].split("/"))
        return (1, 0, parts)
    return (2, 0, ((1, 0, loc),))


def record_line(file: str, loc: str, patient: Optional[str], status: str) -> Dict[str, Any]:
    return {"file": file, "loc": loc, "patient": patient, "status": status}


def sort_records(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(lines, key=lambda r: (r["file"], loc_key(r["loc"])))


def records_text(lines: List[Dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines)


def peak_rss_mb() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1048576 if sys.platform == "darwin" else r / 1024, 1)
    except Exception:  # noqa: BLE001 - not available on every OS
        return 0.0


def build_report(files: List[Dict[str, Any]], counts: Dict[str, int], entities: Dict[str, int],
                 seconds: float) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "files": files,
        "counts": dict(counts),
        "entities": {k: int(entities[k]) for k in sorted(entities)},
        "timing": {"seconds": round(float(seconds), 2)},
        "resources": {"peak_rss_mb": peak_rss_mb()},
    }


def report_text(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def file_entry(sha: str, output: Optional[str], reason: str = "") -> Dict[str, Any]:
    if output is not None:
        return {"input_sha256": sha, "output": output, "status": "sanitized"}
    return {"input_sha256": sha, "output": None, "status": "quarantined", "reason": reason or "internal_error"}
