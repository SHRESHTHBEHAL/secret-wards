# Raksha: a privacy firewall for multilingual Indian hospital records

**Yugaantar DevForge 2026 · Track 3 "Secret Wards" · team 404FoundUs**

Raksha turns a messy dump of hospital records (CSV, TSV, JSON, FHIR R4 bundles, free-text notes, in English,
Devanagari Hindi, Hinglish and nine more Indian scripts) into a research release that:

* removes every personal identifier, including the ones hidden in file names, JSON keys, CSV headers, metadata
  and base64 attachments;
* keeps every medical value exactly (medicines, doses, `1-0-1` frequencies, vitals, labs with units, diagnoses,
  stay lengths);
* gives each real patient **one keyed pseudonym across files, hospitals and scripts**, and never merges two people
  who only share a name;
* generalises quasi-identifiers per patient so that a voter-roll attacker cannot single people out, and **measures**
  that with a replica of the published attacker.

Offline, CPU-only, no LLMs and no pretrained models. Runs on the **Python standard library alone**; `rapidfuzz` is an optional
C++ backend for the same fuzzy distances (byte-identical output with or without it).

| Measured on the practice data | |
|---|---|
| Personal data still visible | **0.0%** (Latin 0.0%, Devanagari 0.0%, Hinglish 0.0%; file names, keys, headers, metadata, base64 0.0%) |
| Canaries found in the output | 0 / 4 |
| Medical values kept | 98.5% |
| Linking precision / recall / F0.5 | 1.00 / 1.00 / 1.00 (no wrong merges) |
| Re-identification risk (replica attacker, A1-A7) | combined **13.0%** (resistance 0.87); record linkage 5.7% of raw, profile re-identification 10.4%; 0.4% of records unique in the registry (raw 60.8%) |
| Run time / peak memory | 2.0 s / 49 MB for 200 files; 34 s / 295 MB for 5,000 files (growth exponent 1.0; limit 15 min / 4 GB) |
| On data we never tuned on | generated unseen-format sets (`scripts/chaos.py`, ten seeds): 0.0% leaked, no wrong merges. Hand-written suites in formats the rules had never met: 1.8% to 10.8% leaked at first sight, each gap then closed with a general rule and a test (see [docs/BENCHMARK.md](docs/BENCHMARK.md) and Known limitations) |

## Setup and run

```bash
python -m pip install -r requirements.txt     # optional rapidfuzz; Python 3.9+ standard library otherwise
RAKSHA_SECRET=<secret> python main.py --input <input dir> --output <empty output dir>
```

Output: `sanitized/` (same paths and formats as the input; files whose *names* held PII are renamed),
`report.json` (every input by SHA-256, true counts, timing, memory) and `records.jsonl` (record -> pseudonym).
`raksha.toml` holds the evaluator commands. The secret is read from the environment only and never written.

Local checks with the organisers' kit cloned next to this repo:

```bash
scripts/dev.sh                                   # run on dev/input, validate_output.py, check_dev.py
python3 scripts/attack.py --release my_output --dev ../Secret-Wards-ToolKit/dev    # replica attacker
python -m unittest discover -s tests             # 570 tests
```

## Architecture

```
 input/ ─► 1 INGEST ─► 2 HARVEST ─► 3 LINK ─► 4 PSEUDONYMS ─► 5 PRIVACY PLAN ─► 6 SANITIZE ─► 7 LEAK GATE ─► output/
           decode,      identity     blocking,  HMAC-SHA256     per-patient band,   typed fields,   known-identity    sanitized/
           sniff,       facts of     rules,     subkeys from    small-cell geo,     free text,      scan of every     report.json
           quarantine   every file   cannot-    RAKSHA_SECRET   DOB removed,        FHIR, names,    output channel    records.jsonl
                                     link                       collision-free      keys, headers   (incl. base64)
                                                                date shifts
```

Two passes: identity facts are harvested from **every** file before anything is written, so an identifier learned
in a registration CSV is also removed from a nursing note, a file name or a base64 attachment elsewhere.

| Stage | Module | How |
|---|---|---|
| Ingest | `raksha/ingest.py` | Format decided from content, not extension (a JSON file named `.csv` is JSON). UTF-8, UTF-8-BOM, UTF-16 (with or without BOM), cp1252. Broken, truncated, empty, binary, PDF, XML and over-deep JSON files are **quarantined with a reason code**, never copied; symlinks that leave the input folder are never followed. |
| Field typing | `raksha/fields.py` | CSV headers and JSON key paths typed by word stems (English, Hinglish, Hindi and the folded Indian scripts) plus value-shape voting; an untyped column whose values are ID-shaped and near-unique is treated as an identifier whatever its header says. |
| Free-text detection | `raksha/detect.py`, `patterns.py`, `dates.py` | Layered rules: identifier recognisers (Aadhaar with Verhoeff checksum, ABHA, PAN, UHID / MRN / IPD / OPD, insurance, phones in every format and digit script), labels (`Name:`, `मरीज़ का नाम:`, `রোগীর নাম:` ...), kinship anchors (S/o, W/o, D/o, C/o, पति, ਪਤੀ, తండ్రి ...), honorifics (ji, sahab, didi, garu), address parsing, place phrases ("ghar X mein hai"), names in export paths. **Protected clinical spans** (doses, `1-0-1`, vitals, labs with units, eponyms such as Parkinson's, doctor lines, wards, ASHA) are never redacted, which resolves the meaning traps ("C/O fever" vs "C/O Ramesh", "Dr. Ramesh" vs relative Ramesh). |
| Lexicons | `raksha/lexicon.py`, `scripts.py` | Clinical, complaint, kinship, honorific, title and address-cue word lists in every supported script. No patient names are hard-coded. |
| Transliteration and phonetic keys | `raksha/translit.py` | Devanagari -> Latin with schwa handling, then a **phonetic key** per name token (aspirates, vowel length, w/v, z/j, q/k, doubled letters, Mohammad / Mohd / Md), compared with a bounded **fuzzy edit distance** (Levenshtein; `rapidfuzz` when installed, identical pure-Python fallback) that tolerates vowel slips when the consonant skeleton matches. Honorifics and generic parts (Kumar, Devi, Singh) never identify on their own. |
| Multi-script | `raksha/scripts.py` | Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam and Urdu are folded onto Devanagari **one code point for one** (the Brahmic blocks share Devanagari's layout at a fixed offset; Urdu uses a phonetic table). Spans found on folded text index the original, so every detector and the name keys work on 11 scripts and the output keeps its script. See [docs/MULTILINGUAL.md](docs/MULTILINGUAL.md). |
| Linkage | `raksha/link.py` | Union-find with blocking by identifier and by phonetic name key. Rules in order of strength: shared UHID / encounter / Aadhaar / ABHA / PAN / email; shared phone only when the names are compatible; name + DOB; name + relative; name + village + age ±1; first-name fragments ("Meera, W/o Rajan") only when exactly one candidate exists. **Cannot-link constraints** (different gender, DOB, Aadhaar, ABHA, PAN, birth years more than 2 apart) are checked on whole groups, so transitive chains cannot over-merge; an identifier shared by incompatible names is demoted; ambiguous evidence gives `patient: null`. |
| Pseudonyms | `raksha/pseudo.py` | `PSN-` + 10 Crockford characters of **HMAC-SHA256** under a subkey derived from `RAKSHA_SECRET`; a pseudonym never contains the patient's own ID digits. A different secret gives different pseudonyms and shifts; the same secret gives byte-identical output. |
| Privacy layer | `raksha/privacy.py`, `pseudo.ShiftBook`, `config/policy.yaml` | Dates of birth removed (FHIR `birthDate` dropped); one 10-year age band per patient across all records (85+ top band); district and PIN prefix kept only when at least 3 patients share the (district, gender, band) cell; **per-patient date shifts of 30-180 days, collision-free**, so no two patients share an offset and the attacker cannot recover a global shift; FHIR `meta.lastUpdated` and `Bundle.timestamp` shifted too. Intervals and lengths of stay stay exact. |
| Sanitize | `raksha/sanitize.py` | Format-preserving rewrite: CSV keeps columns and rows, JSON keeps key paths and value types, FHIR stays valid R4 (ids, references, narratives, base64 attachments decoded -> scrubbed -> re-encoded). The pseudonym is written into the record's name or ID slot. |
| Leak gate | `raksha/gate.py` | Final scan of every output channel (content, file names, keys, headers, `report.json`, `records.jsonl`) for any identifier or name learned anywhere, across Indic digits, separators and base64 / percent / HTML-entity encodings, streamed to cap memory. A file that still leaks after cleaning is quarantined. |

## Privacy-utility trade-off

Each setting in `config/policy.yaml` was chosen by measuring both sides on the practice data
(`scripts/attack.py` for privacy, `check_dev.py` for utility):

| Decision | Privacy effect (replica attacker) | Utility cost |
|---|---|---|
| Remove DOB (never a shifted DOB) | resistance 0.61 -> 0.72 | DOB generalisation credit |
| One 10-year band per patient (not 5-year per record) | 0.72 -> 0.77 | age-band detail |
| District and PIN prefix only in cells of >= 3 patients | 0.77 -> 0.87 | 1.5% of medical probes (district mentions) |
| Shift FHIR `meta` and `Bundle.timestamp` | cross-release date stability 2.7% -> 0% | none |
| Collision-free date shifts | no global shift to recover while offsets remain | none |
| Generalise rare diagnoses | **rejected**: +0.01 resistance for 23% of diagnoses changed | — |

## Security design

* **No intermediate data at rest.** Everything is held in memory and only the output folder is written; no temp
  files, caches or logs (`tests/test_robustness.py` runs with private, empty `TMPDIR` and `HOME` and asserts they
  stay empty).
* **Keys away from data.** `RAKSHA_SECRET` is read from the environment and expanded into HMAC subkeys; the key
  object hides itself from `repr` and refuses to be pickled. Nothing secret is ever written.
* **PII-free logging.** stderr carries only `raksha: <ExceptionClass> in <stage>`; never values, paths or messages.
* **Quarantine, not pass-through.** Unsafe files are listed in `report.json` by SHA-256 and reason code only; their
  bytes never reach `sanitized/`. A crash still leaves a valid report.
* **Assume breach.** The release is the only artefact and is designed to be safe to leak (replica attacker above);
  releases under different secrets cannot be linked to each other (cross-release risk 0%).

## Models declared

None. Rules, word lists, transliteration tables, phonetic keys and edit-distance matching only; no LLMs, no
generative models and no trained or pretrained ML models. Only optional dependency: `rapidfuzz` (string distances;
the output is byte-identical without it).

## Known limitations

* Unfamiliar file layouts are the main risk. A layout the parsers do not recognise is cleaned as free text, and
  XML, HTML and HL7 content is quarantined rather than rewritten: nothing leaks, but that file's clinical content
  is not released. On hand-written suites in new formats, first-sight leakage was 1.8% to 10.8%.
* Lab, bill, visit and queue-token numbers are kept as clinical context, not treated as patient identifiers.
* The targeted attack still succeeds for about 43% of known-fact targets on the practice data: rare diagnoses and
  exact stay lengths survive by design, because they are the clinical value. Generalising rare diagnoses cost more
  utility than it bought privacy.
* Tamil script has no separate voiced consonants and Urdu leaves short vowels implicit, so some cross-script name
  keys differ from their Latin spelling; linking then abstains rather than guesses.
* The broad free-text name net can still take an unknown capitalised phrase for a person ("Information Leaflet"),
  a small over-redaction that we accept to catch unlabelled names.
* 10-year bands are coarser than the 5-year bands a researcher may prefer; the policy file makes this one line.

## Repository

```
main.py                 entry point (never raises; writes a valid report on any failure)
raksha/                 the pipeline (modules above)
config/policy.yaml      privacy policy, every number measured
scripts/attack.py       replica of the published attacker (dev only, never imported by the pipeline)
scripts/chaos.py        rewrites the practice set with unseen names, labels, ID and date formats
scripts/synth_gen.py    fresh synthetic dataset with truth; scripts/score_composite.py scores it
scripts/stress.py       scaling and resource stress test
tests/                  570 unit, robustness and unseen-format tests
docs/                   multi-script design, generalisation benchmark, project brief (brief.pdf)
```
