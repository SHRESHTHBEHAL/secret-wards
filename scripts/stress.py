#!/usr/bin/env python3
"""Scale test: build an N-times replica of an input tree and time the pipeline on it.

Every replica gets its own identities so patients do not collide across replicas:
  * digit runs of 5+ (and 4-4-4 groups) keep their first digit and have the rest mapped through a
    per-replica digit permutation (consistent inside a replica, so links survive);
  * Latin name tokens (read at run time from an optional registry CSV, never hardcoded) get a
    per-replica Latin suffix; Devanagari words get a per-replica Devanagari suffix.
Replica 0 is the input unchanged. Nothing is written inside the repository; data values are
never printed.

Usage:
  python3 scripts/stress.py --input <dev/input> [--registry <attacker/registry.csv>] \
      [--sizes 1,5,10,25] [--work <scratch dir>] [--profile N] [--python <interpreter>]
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO = Path(__file__).resolve().parent.parent
_DIGITS = re.compile(r"\d{4}[ -]\d{4}[ -]\d{4}|\d{5,}")
_DEVA = re.compile("[ऀ-ॿ]{2,}")
_LATIN_SYL = ["ra", "vi", "ka", "lo", "mi", "su", "de", "pa", "no", "ti", "ga", "re", "bu", "ze", "ho"]
_DEVA_SYL = ["रा", "वि", "का", "लो", "मी", "सु", "दे", "पा", "नो", "ती", "गा", "रे", "बु", "जे", "हो"]


def _suffix(r: int, syl: List[str]) -> str:
    out = ""
    r -= 1
    while True:
        out += syl[r % len(syl)]
        r //= len(syl)
        if r == 0:
            return out
        r -= 1


class Replica:
    def __init__(self, r: int, name_tokens: Set[str]) -> None:
        self.r = r
        rng = random.Random("replica-%d" % r)
        perm = list("0123456789")
        while r and perm == list("0123456789"):
            rng.shuffle(perm)
        self.table = str.maketrans("0123456789", "".join(perm))
        self.lat = _suffix(r, _LATIN_SYL) if r else ""
        self.dev = _suffix(r, _DEVA_SYL) if r else ""
        toks = sorted(name_tokens, key=lambda t: (-len(t), t))
        self.name_rx = re.compile(r"\b(" + "|".join(re.escape(t) for t in toks) + r")\b",
                                  re.IGNORECASE) if toks else None

    def text(self, s: str) -> str:
        if not self.r:
            return s
        s = _DIGITS.sub(lambda m: m.group(0)[0] + m.group(0)[1:].translate(self.table), s)
        if self.name_rx is not None:
            s = self.name_rx.sub(lambda m: m.group(0) + (self.lat.upper() if m.group(0).isupper() else self.lat), s)
        return _DEVA.sub(lambda m: m.group(0) + self.dev, s)

    def data(self, raw: bytes) -> bytes:
        if not self.r:
            return raw
        for bom, codec in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
            if raw.startswith(bom):
                try:
                    return bom + self.text(raw[len(bom):].decode(codec)).encode(codec)
                except UnicodeError:
                    return raw
        try:
            return self.text(raw.decode("utf-8")).encode("utf-8")
        except UnicodeError:
            return raw  # cp1252 / binary / broken: copied as is


def load_name_tokens(registry: Optional[Path]) -> Set[str]:
    toks = set()  # type: Set[str]
    if not registry or not registry.is_file():
        return toks
    with open(str(registry), encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for col in ("name", "relative_name", "village", "mohalla"):
                for t in re.findall(r"[A-Za-z]{3,}", row.get(col) or ""):
                    toks.add(t)
    return toks


def build(src: Path, dst: Path, n: int, names: Set[str]) -> int:
    if dst.exists():
        shutil.rmtree(str(dst))
    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink())
    count = 0
    for r in range(n):
        rep = Replica(r, names)
        for p in files:
            rel = p.relative_to(src).as_posix()
            out = dst / ("rep%03d" % r) / rep.text(rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(rep.data(p.read_bytes()))
            count += 1
    return count


_RUN_KEY = __import__("secrets").token_hex(16)

def run_once(py: str, inp: Path, out: Path, tmp: Path, profile: Optional[Path]) -> Dict[str, float]:
    if out.exists():
        shutil.rmtree(str(out))
    tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMPDIR=str(tmp), HOME=str(tmp))
    env["RAKSHA_SECRET"] = _RUN_KEY          # random per stress run, never a literal
    cmd = [py]
    if profile:
        cmd += ["-m", "cProfile", "-o", str(profile)]
    cmd += [str(REPO / "main.py"), "--input", str(inp), "--output", str(out)]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, status, ru = os.wait4(proc.pid, 0)
    wall = time.monotonic() - t0
    err = proc.stderr.read() if proc.stderr else b""
    proc.returncode = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8
    rss = ru.ru_maxrss / (1048576.0 if sys.platform == "darwin" else 1024.0)
    nrec = 0
    rp = out / "records.jsonl"
    if rp.is_file():
        with open(str(rp), "rb") as fh:
            nrec = sum(1 for _ in fh)
    return {"wall": wall, "rss": rss, "code": proc.returncode, "records": nrec, "stderr_lines": len(err.splitlines())}


def exponent(pts: List[List[float]]) -> float:
    xs = [math.log(p[0]) for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--registry", default=None, help="optional CSV with name columns used to vary names")
    ap.add_argument("--sizes", default="1,5,10,25")
    ap.add_argument("--work", default=None, help="scratch directory (default: a new temp dir, removed after)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--profile", type=int, default=0, help="also profile the run of this size (cProfile, top 25)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    src = Path(a.input).resolve()
    work = Path(a.work).resolve() if a.work else Path(tempfile.mkdtemp(prefix="raksha-stress-"))
    if work == REPO or REPO in work.parents:
        sys.stderr.write("stress: --work must be outside the repository\n")
        return 2
    names = load_name_tokens(Path(a.registry) if a.registry else None)
    sizes = [int(s) for s in a.sizes.split(",") if s.strip()]
    print("%5s %7s %9s %9s %8s %5s" % ("N", "files", "records", "wall_s", "rss_mb", "exit"))
    pts = []
    try:
        for n in sizes:
            inp = work / ("in_%d" % n)
            nfiles = build(src, inp, n, names)
            prof = work / ("prof_%d.out" % n) if a.profile == n else None
            res = run_once(a.python, inp, work / ("out_%d" % n), work / ("tmp_%d" % n), prof)
            leftovers = list((work / ("tmp_%d" % n)).iterdir())
            print("%5d %7d %9d %9.2f %8.1f %5d%s%s" % (
                n, nfiles, res["records"], res["wall"], res["rss"], res["code"],
                "  stderr:%d" % res["stderr_lines"] if res["stderr_lines"] else "",
                "  TMP/HOME LEFTOVERS:%d" % len(leftovers) if leftovers else ""))
            pts.append([n, res["wall"]])
            shutil.rmtree(str(inp), ignore_errors=True)
            shutil.rmtree(str(work / ("out_%d" % n)), ignore_errors=True)
            if prof and prof.is_file():
                import pstats
                print("\nprofile N=%d (cumulative, top 25):" % n)
                pstats.Stats(str(prof)).sort_stats("cumulative").print_stats(25)
                print("profile N=%d (tottime, top 25):" % n)
                pstats.Stats(str(prof)).sort_stats("tottime").print_stats(25)
        if len(pts) >= 2:
            print("growth exponent (least squares, log wall vs log N): %.3f" % exponent(pts))
            for (n0, t0), (n1, t1) in zip(pts, pts[1:]):
                print("  %d -> %d: %.3f" % (n0, n1, math.log(t1 / t0) / math.log(n1 / n0)))
    finally:
        if not a.work:
            shutil.rmtree(str(work), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
