# Secret Wards: privacy firewall for multilingual hospital records

Yugaantar DevForge 2026, Track 3. An offline, CPU-only, LLM-free pipeline that
de-identifies synthetic Indian hospital records (English, Devanagari Hindi, Hinglish),
links the same patient across files and scripts under a keyed pseudonym, and keeps
clinical values intact.

> Status: skeleton. Built on the organisers' `starter/` (contract-correct I/O only);
> detection, linkage and privacy layers are being written during the event.

## Setup

```bash
pip install -r requirements.txt
```

Python 3.10+. No network access is used at run time.

## Run

```bash
RAKSHA_SECRET=<secret> python main.py --input <input dir> --output <empty output dir>
```

Output: `sanitized/` (same paths and formats as the input), `report.json`, `records.jsonl`.

### Local dev loop

With the organisers' toolkit cloned next to this repo (`../Secret-Wards-ToolKit`):

```bash
scripts/dev.sh
```

Runs the pipeline on the practice data, then `validate_output.py` (must print
`CONTRACT OK`) and `check_dev.py`.

## Architecture

_TODO: diagram._ Ingestion → detection (3 scripts) → linkage & HMAC pseudonyms →
privacy layer (quasi-identifiers) → leak re-scan → export.

## Models declared

None. Rules, gazetteers and classical methods only (no LLMs, no pretrained transformers).

## Privacy policy

See `config/policy.yaml`.

## Known limitations

_TODO._
