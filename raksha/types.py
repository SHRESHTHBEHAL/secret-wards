"""Shared data shapes passed between pipeline stages. Standard library only, Python 3.9+."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

# ParsedFile.kind values
KIND_CSV = "csv"            # header + rows (delimiter kept)
KIND_JSON = "json"          # any parsed JSON that is not a FHIR Bundle
KIND_FHIR = "fhir"          # parsed JSON with resourceType == "Bundle"
KIND_TEXT = "text"          # free-text document
KIND_QUARANTINE = "quarantine"

# Typed identifier tokens look like "<type>:<normalised value>".
ID_UHID = "uhid"            # hospital / registration number of a patient
ID_ENC = "enc"              # encounter number: IPD, ADM, admission
ID_AADHAAR = "aadhaar"
ID_ABHA = "abha"
ID_ABHA_ADDR = "abhaaddr"
ID_PAN = "pan"
ID_INS = "ins"
ID_EMAIL = "email"
ID_PHONE = "phone"


@dataclass
class ParsedFile:
    rel: str                                  # input path relative to the input root, posix style
    sha256: str                               # hash of the raw bytes
    kind: str                                 # one of the KIND_* values
    reason: str = ""                          # quarantine reason code (never contains data)
    text: str = ""                            # decoded text (empty when quarantined)
    delimiter: str = ","                      # csv only
    header: List[str] = field(default_factory=list)       # csv only
    rows: List[List[str]] = field(default_factory=list)   # csv only, ragged rows kept as read
    data: Any = None                          # json / fhir only


@dataclass
class Span:
    start: int
    end: int
    kind: str                                 # e.g. PHONE, AADHAAR, NAME, DOCTOR, DOSE
    value: str = ""                           # normalised value when useful (digits, ISO date)


@dataclass
class Facts:
    """Identity evidence harvested from one record."""
    names: List[str] = field(default_factory=list)                 # patient name surfaces, any script
    relatives: List[Tuple[str, str]] = field(default_factory=list) # (relation word, relative name)
    ids: List[str] = field(default_factory=list)                   # typed tokens, e.g. "uhid:SNJ26064371"
    raw_ids: List[str] = field(default_factory=list)               # original surfaces of every identifier
    dob: Optional[dt.date] = None
    age: Optional[int] = None
    gender: str = ""                                               # "M", "F" or ""
    village: str = ""
    tehsil: str = ""
    district: str = ""
    pin: str = ""
    address_parts: List[str] = field(default_factory=list)         # house, locality, landmark surfaces
    ref_date: Optional[dt.date] = None                             # a date of the record (for age-at-date)
    is_patient: bool = True                                        # False for visitor / helpdesk style records


@dataclass
class Record:
    rel: str                                  # file the record lives in (input relative path)
    loc: str                                  # "row:N", a JSON pointer, or "doc"
    facts: Facts = field(default_factory=Facts)


@dataclass
class Patient:
    key: str                                  # canonical key (stable, derived from the evidence)
    records: List[Tuple[str, str]] = field(default_factory=list)   # (rel, loc)
    facts: List[Facts] = field(default_factory=list)               # every fact sheet merged into this patient
