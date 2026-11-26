"""Privacy policy loader: a tiny `key: value` reader (no PyYAML). Standard library only, Python 3.9+."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

DEFAULTS = {
    "age_band_years": 5,
    "age_top": 85,
    "date_shift_max_days": 180,
    "date_shift_min_days": 30,
    "rare_k": 3,
    "rare_cap_pct": 8,
    "rare_rule": "on",
}  # type: Dict[str, Any]


def load_policy(path: Path) -> Dict[str, Any]:
    """Defaults overlaid with `key: value` lines from `path` (missing file -> defaults)."""
    policy = dict(DEFAULTS)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return policy
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if not k:
            continue
        policy[k] = int(v) if v.lstrip("-").isdigit() else v
    return policy
