# Generalisation benchmark (data we never tuned on)

The practice set is too small and too familiar to show how the pipeline behaves on the hidden datasets,
so we measure on data with **new hospitals, name pools, villages, ID formats, labels and scripts**.

| Set | How it is made | Leaked PII | Medical kept | Linking F0.5 | Composite* |
|---|---|---:|---:|---:|---:|
| practice (dev) | organisers | 0.0% | 98.5% | 1.00 | — |
| synthetic A (tuning) | `scripts/synth_gen.py out 20261126` | 0.0% | 99.1% | 1.00 | 98.2 |
| synthetic B (held out) | `scripts/synth_gen.py out 99` | 0.0% | 99.5% | 1.00 | 98.3 |
| synthetic seed 5 (held out) | `scripts/synth_gen.py out 5` | — | — | — | 98.4 |
| chaos 7 / 8 / 9 (held out) | `scripts/chaos.py --level 3 --seed N` | 0.0% | 98.5% | 1.00 | — |
| 10 native-script notes | `tests/test_scripts.py` | 0 / 32 | 16 / 16 | — | — |
| new layouts x 8 seeds (held out) | `scripts/synth_gen2.py out N`: native-script notes in 8 languages, WhatsApp, e-mail, HL7, JSONL, nested JSON, headerless CSV, patient-named folders, data-URI attachments | 0.0% | 99.6-100% | 1.00 | — |
| chaos x 6 more seeds, synthetic x 6 more seeds (held out) | as above | 0.0% | 98.5-100% | 1.00 | — |
| 4 hand-written suites in formats the rules had never met (first sight, before any fix) | written separately from the generators; kept outside this repository | 1.8% / 10.8% / 5.9% / 2.8% | not recorded at first sight; 88-99% after fixes | wrong pairs at first sight 15 / 147 / 77 / 28; precision 0.86-1.00 after fixes | — |

\* `scripts/score_composite.py` follows docs/SCORING.md and scoring.toml for every computable part; the
hidden attacker is approximated by direct-identifier and quasi-identifier exposure, so use
`scripts/attack.py` for the privacy number (practice: combined risk 11.7%, resistance 0.88).

**Where it is weakest.** The generated sets above share their generators' habits with the rules, so 0.0% on them
is the easy case. The hand-written suites are the honest one: every one exposed layouts the parsers had not seen
(1.8% to 10.8% leaked at first sight, one canary on the fourth). Each gap was then closed with a general rule
and a unit test, never a rule for one file; the README lists what remains under Known limitations.

**Reference point.** On synthetic A a frontier LLM (Claude Opus, doing the de-identification by hand,
which the rules forbid; used only as a ceiling) scored 94.5 on the same scorer: 342 s for 41 files and not
deterministic. Raksha: 98.2 in under a second, deterministic, offline, CPU-only.

## Reproduce

```bash
python3 scripts/synth_gen.py /tmp/synth 99
RAKSHA_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(16))')" python3 main.py --input /tmp/synth/input --output /tmp/out
python3 ../Secret-Wards-ToolKit/check_dev.py --output /tmp/out --truth /tmp/synth/truth/truth.json
python3 scripts/score_composite.py /tmp/out /tmp/synth/truth/truth.json /tmp/synth/input --wall 1 --rss 50 --deterministic 1
```
