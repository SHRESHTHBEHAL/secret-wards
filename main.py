#!/usr/bin/env python3
"""raksha: privacy firewall for hospital records. Thin entry point.

Usage: RAKSHA_SECRET=... python3 main.py --input <input dir> --output <output dir>
(--input / --output fall back to RAKSHA_INPUT / RAKSHA_OUTPUT). Standard library only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def main() -> int:
    ap = argparse.ArgumentParser(description="raksha privacy firewall")
    ap.add_argument("--input", default=os.environ.get("RAKSHA_INPUT"))
    ap.add_argument("--output", default=os.environ.get("RAKSHA_OUTPUT"))
    a = ap.parse_args()
    if not a.input or not a.output:
        sys.stderr.write("raksha: --input and --output are required\n")
        return 2
    inp, out = Path(a.input), Path(a.output)
    try:
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
        from raksha.pipeline import run
        from raksha.policy import load_policy
        policy = load_policy(HERE / "config" / "policy.yaml")
        secret = os.environ.get("RAKSHA_SECRET", "").encode("utf-8")
        return run(inp, out, secret, policy)
    except BaseException as exc:  # noqa: BLE001 - last resort: still leave a valid report
        if isinstance(exc, SystemExit):
            raise
        try:
            sys.stderr.write("raksha: %s in main\n" % type(exc).__name__)
        except Exception:  # noqa: BLE001
            pass
        try:
            from raksha.pipeline import emergency_report
            return emergency_report(inp, out)
        except BaseException:  # noqa: BLE001
            return 1


if __name__ == "__main__":
    sys.exit(main())
