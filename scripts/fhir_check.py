#!/usr/bin/env python3
"""Structural FHIR R4 validator for Bundles (JSON). Standard library only, Python 3.9+.

Usage: python3 scripts/fhir_check.py <dir or file> [--compare <input dir or file>] [-v]

Prints, per file and in total, the number of problems by kind; always exits 0.
With --compare, the output bundle is also diffed against the input bundle of the same relative
path (or the same file name): resource count / types / ids / fullUrls / reference strings must be
identical, key paths must match, and value types must not change. Problems already present in the
input are reported separately ("inherited") and are not counted against the output.
"""
from __future__ import annotations

import base64
import binascii
import calendar
import collections
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ----------------------------------------------------------------------------- R4 vocabulary

RESOURCE_TYPES = frozenset("""
Account ActivityDefinition AdverseEvent AllergyIntolerance Appointment AppointmentResponse AuditEvent
Basic Binary BiologicallyDerivedProduct BodyStructure Bundle CapabilityStatement CarePlan CareTeam
CatalogEntry ChargeItem ChargeItemDefinition Claim ClaimResponse ClinicalImpression CodeSystem
Communication CommunicationRequest CompartmentDefinition Composition ConceptMap Condition Consent
Contract Coverage CoverageEligibilityRequest CoverageEligibilityResponse DetectedIssue Device
DeviceDefinition DeviceMetric DeviceRequest DeviceUseStatement DiagnosticReport DocumentManifest
DocumentReference EffectEvidenceSynthesis Encounter Endpoint EnrollmentRequest EnrollmentResponse
EpisodeOfCare EventDefinition Evidence EvidenceVariable ExampleScenario ExplanationOfBenefit
FamilyMemberHistory Flag Goal GraphDefinition Group GuidanceResponse HealthcareService ImagingStudy
Immunization ImmunizationEvaluation ImmunizationRecommendation ImplementationGuide InsurancePlan
Invoice Library Linkage List Location Measure MeasureReport Media Medication MedicationAdministration
MedicationDispense MedicationKnowledge MedicationRequest MedicationStatement MedicinalProduct
MedicinalProductAuthorization MedicinalProductContraindication MedicinalProductIndication
MedicinalProductIngredient MedicinalProductInteraction MedicinalProductManufactured
MedicinalProductPackaged MedicinalProductPharmaceutical MedicinalProductUndesirableEffect
MessageDefinition MessageHeader MolecularSequence NamingSystem NutritionOrder Observation
ObservationDefinition OperationDefinition OperationOutcome Organization OrganizationAffiliation
Parameters Patient PaymentNotice PaymentReconciliation Person PlanDefinition Practitioner
PractitionerRole Procedure Provenance Questionnaire QuestionnaireResponse RelatedPerson RequestGroup
ResearchDefinition ResearchElementDefinition ResearchStudy ResearchSubject RiskAssessment
RiskEvidenceSynthesis Schedule SearchParameter ServiceRequest Slot Specimen SpecimenDefinition
StructureDefinition StructureMap Subscription Substance SubstanceNucleicAcid SubstancePolymer
SubstanceProtein SubstanceReferenceInformation SubstanceSourceMaterial SubstanceSpecification
SupplyDelivery SupplyRequest Task TerminologyCapabilities TestReport TestScript ValueSet
VerificationResult VisionPrescription
""".split())

BUNDLE_TYPES = {"document", "message", "transaction", "transaction-response", "batch", "batch-response",
                "history", "searchset", "collection"}
GENDER = {"male", "female", "other", "unknown"}
NAME_USE = {"usual", "official", "temp", "nickname", "anonymous", "old", "maiden"}
CP_SYSTEM = {"phone", "fax", "email", "pager", "url", "sms", "other"}
CP_USE = {"home", "work", "temp", "old", "mobile"}
ADDR_USE = {"home", "work", "temp", "old", "billing"}
ADDR_TYPE = {"postal", "physical", "both"}
ID_USE = {"usual", "official", "temp", "secondary", "old"}
NARR_STATUS = {"generated", "extensions", "additional", "empty"}

# (resourceType) -> (required elements, {element: value set}, references that must be present)
STATUS = {
    "Composition": {"preliminary", "final", "amended", "entered-in-error"},
    "Encounter": {"planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled",
                  "entered-in-error", "unknown"},
    "Observation": {"registered", "preliminary", "final", "amended", "corrected", "cancelled",
                    "entered-in-error", "unknown"},
    "MedicationRequest": {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped",
                          "draft", "unknown"},
    "Procedure": {"preparation", "in-progress", "not-done", "on-hold", "stopped", "completed",
                  "entered-in-error", "unknown"},
    "DocumentReference": {"current", "superseded", "entered-in-error"},
    "DiagnosticReport": {"registered", "partial", "preliminary", "final", "amended", "corrected",
                         "appended", "cancelled", "entered-in-error", "unknown"},
    "Immunization": {"completed", "entered-in-error", "not-done"},
    "ServiceRequest": {"draft", "active", "on-hold", "revoked", "completed", "entered-in-error", "unknown"},
    "MedicationStatement": {"active", "completed", "entered-in-error", "intended", "stopped", "on-hold",
                            "unknown", "not-taken"},
    "CarePlan": {"draft", "active", "on-hold", "revoked", "completed", "entered-in-error", "unknown"},
}
VALUESETS = {
    ("MedicationRequest", "intent"): {"proposal", "plan", "order", "original-order", "reflex-order",
                                      "filler-order", "instance-order", "option"},
    ("ServiceRequest", "intent"): {"proposal", "plan", "directive", "order", "original-order",
                                   "reflex-order", "filler-order", "instance-order", "option"},
    ("CarePlan", "intent"): {"proposal", "plan", "order", "option"},
    ("AllergyIntolerance", "type"): {"allergy", "intolerance"},
    ("AllergyIntolerance", "criticality"): {"low", "high", "unable-to-assess"},
    ("Composition", "confidentiality"): {"U", "L", "M", "N", "R", "V"},
    ("DocumentReference", "docStatus"): {"preliminary", "final", "amended", "entered-in-error"},
}
REQUIRED = {
    "Composition": ["status", "type", "date", "author", "title"],
    "Encounter": ["status", "class"],
    "Condition": ["subject"],
    "Observation": ["status", "code"],
    "MedicationRequest": ["status", "intent", "subject", "medication[x]"],
    "Procedure": ["status", "subject"],
    "DocumentReference": ["status", "content"],
    "AllergyIntolerance": ["patient"],
    "DiagnosticReport": ["status", "code"],
    "RelatedPerson": ["patient"],
    "Immunization": ["status", "vaccineCode", "patient", "occurrence[x]"],
    "ServiceRequest": ["status", "intent", "subject"],
    "MedicationStatement": ["status", "medication[x]", "subject"],
    "CarePlan": ["status", "intent", "subject"],
    "Practitioner": [], "Organization": [], "Patient": [],
}

ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
UUID_RE = re.compile(r"^urn:uuid:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
OID_RE = re.compile(r"^urn:oid:[0-2](\.(0|[1-9][0-9]*))+$")
ABS_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^\s]+$")
MIME_RE = re.compile(r"^[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+(\s*;\s*[A-Za-z0-9_\-]+=[^;\s]+)*$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
TZ = r"(Z|[+\-](0[0-9]|1[0-3]):[0-5][0-9]|[+\-]14:00)"
DATE_RE = re.compile(r"^([0-9]{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?$")
DATETIME_RE = re.compile(r"^([0-9]{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01])"
                         r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?" + TZ + r")?)?)?$")
INSTANT_RE = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
                        r"T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?" + TZ + "$")

DATE_KEYS = {"birthDate"}
DATETIME_KEYS = {"effectiveDateTime", "authoredOn", "recordedDate", "performedDateTime", "date",
                 "onsetDateTime", "abatementDateTime", "deceasedDateTime", "occurrenceDateTime",
                 "valueDateTime", "start", "end", "creation", "assertedDate", "lastOccurrence",
                 "whenHandedOver", "whenPrepared", "dateAsserted"}
INSTANT_KEYS = {"issued", "lastUpdated", "timestamp", "recorded"}
# "date" is only a dateTime in some resources; it is a plain date (or absent) elsewhere: treated as
# dateTime (a superset of date). "start"/"end" checked inside period only.
PERIOD_KEYS = {"start", "end"}
DECLARED_REMOVALS = {"birthDate", "_birthDate"}   # generalisable path: may be dropped by policy


class Problems:
    def __init__(self) -> None:
        self.items = []  # type: List[Tuple[str, str, str]]

    def add(self, kind: str, path: str, detail: str = "") -> None:
        self.items.append((kind, path, detail))

    def counts(self) -> collections.Counter:
        return collections.Counter(k for k, _, _ in self.items)


def shape(v: Any) -> str:
    """A non-personal description of a value."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return type(v).__name__
    if isinstance(v, list):
        return "list[%d]" % len(v)
    if isinstance(v, dict):
        return "object{%s}" % ",".join(sorted(v)[:6])
    s = str(v)
    m = re.match(r"^\[[A-Z][A-Z0-9_\-]*\]", s)
    if m:
        return "placeholder %s (len %d)" % (m.group(0), len(s))
    pat = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", s[:40]))
    return "str len %d like %r" % (len(s), pat)


def _real_date(y: int, m: Optional[int], d: Optional[int]) -> bool:
    if m is None:
        return True
    if d is None:
        return 1 <= m <= 12
    return 1 <= m <= 12 and 1 <= d <= calendar.monthrange(y, m)[1]


def check_temporal(v: Any, typ: str, path: str, P: Problems) -> None:
    if not isinstance(v, str):
        P.add("date-syntax", path, "%s must be a string, got %s" % (typ, shape(v)))
        return
    rx = {"date": DATE_RE, "dateTime": DATETIME_RE, "instant": INSTANT_RE}[typ]
    if not rx.match(v):
        P.add("date-syntax", path, "not a FHIR %s: %s" % (typ, shape(v)))
        return
    y = int(v[0:4])
    m = int(v[5:7]) if len(v) >= 7 else None
    d = int(v[8:10]) if len(v) >= 10 else None
    if not _real_date(y, m, d):
        P.add("date-calendar", path, "impossible calendar date")


def _sortkey(v: str) -> str:
    return v[:19]  # good enough for same-zone comparisons


def check_uri(v: Any, path: str, P: Problems) -> bool:
    if not isinstance(v, str) or not v:
        P.add("fullurl", path, "fullUrl not a string: %s" % shape(v))
        return False
    if UUID_RE.match(v) or OID_RE.match(v) or ABS_URL_RE.match(v):
        return True
    P.add("fullurl", path, "fullUrl not urn:uuid / urn:oid / absolute URL: %s" % shape(v))
    return False


def check_narrative(t: Any, path: str, P: Problems) -> None:
    if not isinstance(t, dict):
        return
    if t.get("status") not in NARR_STATUS:
        P.add("narrative", path + ".status", "status not in value set: %s" % shape(t.get("status")))
    div = t.get("div")
    if not isinstance(div, str):
        P.add("narrative", path + ".div", "div missing or not a string")
        return
    if not div.lstrip().startswith("<div"):
        P.add("narrative", path + ".div", "div does not start with <div")
    if 'xmlns="http://www.w3.org/1999/xhtml"' not in div:
        P.add("narrative", path + ".div", "div lacks the XHTML namespace")
    try:
        ET.fromstring(div)
    except ET.ParseError as e:
        P.add("narrative-xml", path + ".div", "not well-formed XML: %s" % str(e).split(":")[0])


def check_attachment(a: Any, path: str, P: Problems) -> None:
    if not isinstance(a, dict):
        P.add("attachment", path, "attachment not an object")
        return
    ct = a.get("contentType")
    if ct is not None and (not isinstance(ct, str) or not MIME_RE.match(ct)):
        P.add("attachment", path + ".contentType", "not a MIME type: %s" % shape(ct))
    data = a.get("data")
    raw = None
    if data is not None:
        if isinstance(data, str):
            data = re.sub(r"\s+", "", data)  # R4 base64Binary tolerates whitespace between quads
        if not isinstance(data, str) or len(data) % 4 or not B64_RE.match(data):
            P.add("base64", path + ".data", "invalid base64 (alphabet/padding): %s" % shape(data)[:30])
        else:
            try:
                raw = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                P.add("base64", path + ".data", "base64 does not decode")
    if "data" in a and "contentType" not in a:
        P.add("attachment", path, "data without contentType")
    size = a.get("size")
    if size is not None:
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            P.add("attachment", path + ".size", "size not an unsignedInt: %s" % shape(size))
        elif raw is not None and size != len(raw):
            P.add("attachment", path + ".size", "size %d != decoded length %d" % (size, len(raw)))
    if "creation" in a:
        check_temporal(a["creation"], "dateTime", path + ".creation", P)


def check_coding(c: Any, path: str, P: Problems) -> None:
    if not isinstance(c, dict):
        P.add("shape", path, "Coding not an object: %s" % shape(c))
        return
    for k in ("system", "code", "display", "version"):
        if k in c and not isinstance(c[k], str):
            P.add("shape", path + "." + k, "Coding.%s not a string: %s" % (k, shape(c[k])))


def check_cc(cc: Any, path: str, P: Problems) -> None:
    if not isinstance(cc, dict):
        P.add("shape", path, "CodeableConcept not an object: %s" % shape(cc))
        return
    cod = cc.get("coding")
    if cod is not None:
        if not isinstance(cod, list):
            P.add("shape", path + ".coding", "coding not a list")
        else:
            for i, c in enumerate(cod):
                check_coding(c, "%s.coding[%d]" % (path, i), P)
    if "text" in cc and not isinstance(cc["text"], str):
        P.add("shape", path + ".text", "CodeableConcept.text not a string")


def check_humanname(n: Any, path: str, P: Problems) -> None:
    if not isinstance(n, dict):
        P.add("shape", path, "HumanName not an object: %s" % shape(n))
        return
    for k in ("given", "prefix", "suffix"):
        if k in n and (not isinstance(n[k], list) or not all(isinstance(x, str) for x in n[k])):
            P.add("shape", path + "." + k, "HumanName.%s must be a list of strings: %s" % (k, shape(n[k])))
    for k in ("family", "text"):
        if k in n and not isinstance(n[k], str):
            P.add("shape", path + "." + k, "HumanName.%s must be a string: %s" % (k, shape(n[k])))
    if "use" in n and n["use"] not in NAME_USE:
        P.add("valueset", path + ".use", "HumanName.use: %s" % shape(n["use"]))


def check_contactpoint(t: Any, path: str, P: Problems) -> None:
    if not isinstance(t, dict):
        P.add("shape", path, "ContactPoint not an object: %s" % shape(t))
        return
    if "system" in t and t["system"] not in CP_SYSTEM:
        P.add("valueset", path + ".system", "ContactPoint.system: %s" % shape(t["system"]))
    if "use" in t and t["use"] not in CP_USE:
        P.add("valueset", path + ".use", "ContactPoint.use: %s" % shape(t["use"]))
    if "value" in t and not isinstance(t["value"], str):
        P.add("shape", path + ".value", "ContactPoint.value not a string")
    if "value" in t and "system" not in t:
        P.add("required", path + ".system", "ContactPoint with value needs system (cpt-2)")


def check_address(a: Any, path: str, P: Problems) -> None:
    if not isinstance(a, dict):
        P.add("shape", path, "Address not an object: %s" % shape(a))
        return
    if "line" in a and (not isinstance(a["line"], list) or not all(isinstance(x, str) for x in a["line"])):
        P.add("shape", path + ".line", "Address.line must be a list of strings: %s" % shape(a["line"]))
    for k in ("text", "city", "district", "state", "postalCode", "country"):
        if k in a and not isinstance(a[k], str):
            P.add("shape", path + "." + k, "Address.%s must be a string: %s" % (k, shape(a[k])))
    if "use" in a and a["use"] not in ADDR_USE:
        P.add("valueset", path + ".use", "Address.use: %s" % shape(a["use"]))
    if "type" in a and a["type"] not in ADDR_TYPE:
        P.add("valueset", path + ".type", "Address.type: %s" % shape(a["type"]))


def check_identifier(i: Any, path: str, P: Problems) -> None:
    if not isinstance(i, dict):
        P.add("shape", path, "Identifier not an object: %s" % shape(i))
        return
    if "value" in i and not isinstance(i["value"], str):
        P.add("shape", path + ".value", "Identifier.value not a string: %s" % shape(i["value"]))
    if "system" in i and not isinstance(i["system"], str):
        P.add("shape", path + ".system", "Identifier.system not a string")
    if "use" in i and i["use"] not in ID_USE:
        P.add("valueset", path + ".use", "Identifier.use: %s" % shape(i["use"]))
    if "type" in i:
        check_cc(i["type"], path + ".type", P)


def check_quantity(q: Any, path: str, P: Problems) -> None:
    if not isinstance(q, dict):
        P.add("shape", path, "Quantity not an object: %s" % shape(q))
        return
    if "value" in q and (not isinstance(q["value"], (int, float)) or isinstance(q["value"], bool)):
        P.add("shape", path + ".value", "Quantity.value must be a number: %s" % shape(q["value"]))
    for k in ("unit", "system", "code"):
        if k in q and not isinstance(q[k], str):
            P.add("shape", path + "." + k, "Quantity.%s not a string" % k)


def walk_generic(node: Any, path: str, P: Problems, refs: List[Tuple[str, str]], parent_key: str = "") -> None:
    """Element-level checks that apply anywhere in a resource."""
    if isinstance(node, dict):
        if not node:
            P.add("empty", path, "empty object")
        for k, v in node.items():
            p = path + "." + k
            if not k or not re.match(r"^_?[A-Za-z][A-Za-z0-9]*(\[x\])?$", k):
                P.add("element-name", p, "not a FHIR element name")
            if v is None:
                P.add("empty", p, "null value")
            elif isinstance(v, str) and v == "":
                P.add("empty", p, "empty string")
            elif isinstance(v, str) and v != v.strip() and k not in ("div", "data"):
                P.add("whitespace", p, "leading/trailing whitespace")
            if k == "reference":
                if isinstance(v, str):
                    refs.append((p, v))
                else:
                    P.add("reference", p, "reference not a string: %s" % shape(v))
            elif k == "text" and isinstance(v, dict) and "div" in v:
                check_narrative(v, p, P)
            elif k in DATE_KEYS:
                check_temporal(v, "date", p, P)
            elif k in INSTANT_KEYS:
                check_temporal(v, "instant", p, P)
            elif k in DATETIME_KEYS and (k not in PERIOD_KEYS or parent_key in ("period", "effectivePeriod",
                                                                                 "performedPeriod",
                                                                                 "onsetPeriod",
                                                                                 "occurrencePeriod")):
                check_temporal(v, "dateTime", p, P)
            if k in ("period", "effectivePeriod", "performedPeriod", "onsetPeriod", "occurrencePeriod") \
                    and isinstance(v, dict):
                s, e = v.get("start"), v.get("end")
                if isinstance(s, str) and isinstance(e, str) and DATETIME_RE.match(s) and DATETIME_RE.match(e) \
                        and len(s) >= 10 and len(e) >= 10 and _sortkey(e) < _sortkey(s):
                    P.add("period-order", p, "period.end before period.start")
            if k in ("attachment", "photo"):
                for j, a in enumerate(v if isinstance(v, list) else [v]):
                    check_attachment(a, p + ("[%d]" % j if isinstance(v, list) else ""), P)
            if k == "valueQuantity" or (k in ("low", "high") and parent_key == "referenceRange"):
                check_quantity(v, p, P)
            if k == "id" and not (isinstance(v, str) and ID_RE.match(v)):
                P.add("id", p, "id syntax: %s" % shape(v))
            if k == "extension" or k == "modifierExtension":
                for j, x in enumerate(v if isinstance(v, list) else []):
                    if not isinstance(x, dict) or not isinstance(x.get("url"), str) or not x.get("url"):
                        P.add("required", "%s[%d].url" % (p, j), "extension.url required")
                if not isinstance(v, list):
                    P.add("shape", p, "extension must be a list")
            walk_generic(v, p, P, refs, k)
    elif isinstance(node, list):
        if not node:
            P.add("empty", path, "empty array")
        for i, v in enumerate(node):
            if v is None:
                P.add("empty", "%s[%d]" % (path, i), "null inside array")
            else:
                walk_generic(v, "%s[%d]" % (path, i), P, refs, parent_key)


def _has(r: Dict[str, Any], el: str) -> bool:
    if el.endswith("[x]"):
        base = el[:-3]
        return any(k.startswith(base) and k[len(base):len(base) + 1].isupper() for k in r)
    v = r.get(el)
    return v is not None and v != [] and v != "" and v != {}


def check_resource(r: Dict[str, Any], path: str, P: Problems) -> None:
    rt = r.get("resourceType")
    for el in REQUIRED.get(rt, []):
        if not _has(r, el):
            P.add("required", path + "." + el, "%s.%s required" % (rt, el))
    if rt in STATUS and "status" in r and r["status"] not in STATUS[rt]:
        P.add("valueset", path + ".status", "%s.status: %s" % (rt, shape(r["status"])))
    for (vrt, el), vs in VALUESETS.items():
        if vrt == rt and el in r and r[el] not in vs:
            P.add("valueset", path + "." + el, "%s.%s: %s" % (rt, el, shape(r[el])))
    if rt in ("Patient", "RelatedPerson", "Practitioner", "Person"):
        if "gender" in r and r["gender"] not in GENDER:
            P.add("valueset", path + ".gender", "gender: %s" % shape(r["gender"]))
        names = r.get("name")
        if names is not None:
            if not isinstance(names, list):
                P.add("shape", path + ".name", "name must be a list of HumanName: %s" % shape(names))
            else:
                for i, n in enumerate(names):
                    check_humanname(n, "%s.name[%d]" % (path, i), P)
    if rt == "Organization" and "name" in r and not isinstance(r["name"], str):
        P.add("shape", path + ".name", "Organization.name must be a string")
    for k, fn in (("telecom", check_contactpoint), ("address", check_address), ("identifier", check_identifier)):
        v = r.get(k)
        if v is None:
            continue
        if not isinstance(v, list):
            single = (k == "identifier" and rt in ("Composition", "QuestionnaireResponse")) or \
                     (k == "address" and rt == "Location")
            if not single:
                P.add("shape", path + "." + k, "%s must be a list: %s" % (k, shape(v)))
            if isinstance(v, dict):
                fn(v, path + "." + k, P)
            continue
        for i, x in enumerate(v):
            fn(x, "%s.%s[%d]" % (path, k, i), P)
    if rt == "Patient":
        for i, c in enumerate(r.get("contact") or [] if isinstance(r.get("contact"), list) else []):
            if isinstance(c, dict):
                if "name" in c:
                    check_humanname(c["name"], "%s.contact[%d].name" % (path, i), P)
                for j, t in enumerate(c.get("telecom") or []):
                    check_contactpoint(t, "%s.contact[%d].telecom[%d]" % (path, i, j), P)
                if "address" in c:
                    check_address(c["address"], "%s.contact[%d].address" % (path, i), P)
        if "multipleBirthInteger" in r and not isinstance(r["multipleBirthInteger"], int):
            P.add("shape", path + ".multipleBirthInteger", "must be an integer")
        for i, l in enumerate(r.get("link") or [] if isinstance(r.get("link"), list) else []):
            if isinstance(l, dict) and l.get("type") not in ("replaced-by", "replaces", "refer", "seealso"):
                P.add("valueset", "%s.link[%d].type" % (path, i), "link.type: %s" % shape(l.get("type")))
    if rt == "Composition":
        if "type" in r:
            check_cc(r["type"], path + ".type", P)
        if "author" in r and not isinstance(r["author"], list):
            P.add("shape", path + ".author", "author must be a list")
        if "title" in r and not isinstance(r["title"], str):
            P.add("shape", path + ".title", "title must be a string")
    if rt == "Encounter" and "class" in r:
        c = r["class"]
        if not isinstance(c, dict) or "coding" in c:
            P.add("shape", path + ".class", "Encounter.class must be a Coding (R4): %s" % shape(c))
        else:
            check_coding(c, path + ".class", P)
    if rt == "Condition":
        for k in ("clinicalStatus", "verificationStatus", "code"):
            if k in r:
                check_cc(r[k], path + "." + k, P)
        cs = ((r.get("clinicalStatus") or {}).get("coding") or [{}])
        if r.get("clinicalStatus") and isinstance(cs, list) and cs and isinstance(cs[0], dict) and \
                cs[0].get("code") not in (None, "active", "recurrence", "relapse", "inactive", "remission",
                                          "resolved"):
            P.add("valueset", path + ".clinicalStatus", "clinicalStatus code: %s" % shape(cs[0].get("code")))
    if rt in ("Observation", "DiagnosticReport", "Procedure", "Immunization", "AllergyIntolerance"):
        if "code" in r:
            check_cc(r["code"], path + ".code", P)
    if rt == "Observation":
        for i, c in enumerate(r.get("component") or [] if isinstance(r.get("component"), list) else []):
            if isinstance(c, dict):
                if "code" not in c:
                    P.add("required", "%s.component[%d].code" % (path, i), "component.code required")
                if "valueQuantity" in c:
                    check_quantity(c["valueQuantity"], "%s.component[%d].valueQuantity" % (path, i), P)
        if "valueInteger" in r and not isinstance(r["valueInteger"], int):
            P.add("shape", path + ".valueInteger", "valueInteger must be an integer")
        if "valueString" in r and not isinstance(r["valueString"], str):
            P.add("shape", path + ".valueString", "valueString must be a string")
    if rt == "MedicationRequest" and "medicationCodeableConcept" in r:
        check_cc(r["medicationCodeableConcept"], path + ".medicationCodeableConcept", P)
    if rt == "DocumentReference":
        content = r.get("content")
        if isinstance(content, list):
            for i, c in enumerate(content):
                if not isinstance(c, dict) or "attachment" not in c:
                    P.add("required", "%s.content[%d].attachment" % (path, i), "content.attachment required")
    if "text" in r and isinstance(r["text"], dict):
        pass  # checked in walk_generic
    elif "text" in r:
        P.add("narrative", path + ".text", "resource text must be a Narrative object")


def check_bundle(b: Any) -> Tuple[Problems, Dict[str, Any]]:
    P = Problems()
    info = {"types": [], "ids": [], "fullUrls": [], "refs": []}  # type: Dict[str, Any]
    if not isinstance(b, dict):
        P.add("bundle", "$", "top level not an object")
        return P, info
    if b.get("resourceType") != "Bundle":
        P.add("bundle", "$.resourceType", "not a Bundle: %s" % shape(b.get("resourceType")))
    if b.get("type") not in BUNDLE_TYPES:
        P.add("valueset", "$.type", "Bundle.type: %s" % shape(b.get("type")))
    if "id" in b and not (isinstance(b["id"], str) and ID_RE.match(b["id"])):
        P.add("id", "$.id", "id syntax: %s" % shape(b["id"]))
    btype = b.get("type")
    if btype == "document":
        if "timestamp" not in b:
            P.add("required", "$.timestamp", "document Bundle needs timestamp (bdl-10)")
        if "identifier" not in b:
            P.add("required", "$.identifier", "document Bundle needs identifier (bdl-9)")
    if "identifier" in b:
        check_identifier(b["identifier"], "$.identifier", P)
    entries = b.get("entry")
    refs = []  # type: List[Tuple[str, str]]
    top = {k: v for k, v in b.items() if k != "entry"}
    walk_generic(top, "$", P, refs)
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        P.add("bundle", "$.entry", "entry not a list")
        entries = []
    targets = set()  # type: Set[str]
    seen = collections.defaultdict(set)  # type: Dict[str, Set[str]]
    full_seen = set()  # type: Set[str]
    contained_ids = collections.defaultdict(set)  # type: Dict[int, Set[str]]
    for i, e in enumerate(entries):
        ep = "$.entry[%d]" % i
        if not isinstance(e, dict):
            P.add("bundle", ep, "entry not an object")
            continue
        r = e.get("resource")
        fu = e.get("fullUrl")
        if fu is not None:
            if check_uri(fu, ep + ".fullUrl", P):
                if fu in full_seen:
                    P.add("fullurl", ep + ".fullUrl", "duplicate fullUrl")
                full_seen.add(fu)
                targets.add(fu)
            info["fullUrls"].append(fu)
        elif btype in ("document", "collection", "message"):
            P.add("fullurl", ep + ".fullUrl", "entry without fullUrl")
        if not isinstance(r, dict):
            P.add("bundle", ep + ".resource", "entry without resource object")
            continue
        rt = r.get("resourceType")
        info["types"].append(rt)
        info["ids"].append(r.get("id"))
        if rt not in RESOURCE_TYPES:
            P.add("resource-type", ep + ".resource.resourceType", "unknown R4 resourceType: %s" % shape(rt))
        rid = r.get("id")
        if rid is not None:
            if isinstance(rid, str) and ID_RE.match(rid):
                if rid in seen[str(rt)]:
                    P.add("id", ep + ".resource.id", "duplicate id within %s" % rt)
                seen[str(rt)].add(rid)
                targets.add("%s/%s" % (rt, rid))
                m = UUID_RE.match(fu) if isinstance(fu, str) else None
                if m and m.group(1).lower() != rid.lower():
                    P.add("id", ep + ".resource.id", "fullUrl urn:uuid does not match id")
                if isinstance(fu, str) and ABS_URL_RE.match(fu):
                    targets.add(fu.rstrip("/").rsplit("/", 2)[-2] + "/" + fu.rstrip("/").rsplit("/", 1)[-1])
        if i == 0 and btype == "document" and rt != "Composition":
            P.add("bundle", ep + ".resource", "document Bundle's first entry must be a Composition")
        for j, c in enumerate(r.get("contained") or [] if isinstance(r.get("contained"), list) else []):
            if isinstance(c, dict):
                if c.get("resourceType") not in RESOURCE_TYPES:
                    P.add("resource-type", "%s.resource.contained[%d]" % (ep, j), "unknown contained type")
                if isinstance(c.get("id"), str):
                    contained_ids[i].add(c["id"])
                check_resource(c, "%s.resource.contained[%d]" % (ep, j), P)
        rrefs = []  # type: List[Tuple[str, str]]
        walk_generic(r, ep + ".resource", P, rrefs)
        check_resource(r, ep + ".resource", P)
        for p, v in rrefs:
            info["refs"].append(v)
            if v.startswith("#"):
                if v[1:] and v[1:] not in contained_ids[i]:
                    P.add("reference", p, "dangling contained reference: %s" % shape(v))
            refs.append((p, v))
    for p, v in refs:
        if v.startswith("#"):
            continue
        if v in targets:
            continue
        # Type/id inside an absolute URL
        m = re.search(r"([A-Z][A-Za-z]+/[A-Za-z0-9\-.]{1,64})(/_history/[^/]+)?$", v)
        if m and m.group(1) in targets and not UUID_RE.match(v):
            continue
        P.add("reference", p, "dangling reference: %s" % shape(v))
    return P, info


# ----------------------------------------------------------------------------- compare

def key_paths(node: Any, path: str = "", out: Optional[Dict[str, Set[str]]] = None) -> Dict[str, Set[str]]:
    if out is None:
        out = collections.defaultdict(set)
    if isinstance(node, dict):
        for k, v in node.items():
            p = path + "." + k
            out[p].add(_tname(v))
            key_paths(v, p, out)
    elif isinstance(node, list):
        for v in node:
            key_paths(v, path + "[]", out)
    return out


def _tname(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if v is None:
        return "null"
    return {dict: "object", list: "array", str: "string"}.get(type(v), type(v).__name__)


def compare(inp: Any, out: Any, iinfo: Dict[str, Any], oinfo: Dict[str, Any], P: Problems) -> None:
    for k in ("types", "ids", "fullUrls"):
        if iinfo[k] != oinfo[k]:
            P.add("compare-" + k, "$", "%d differ (in %d, out %d)" % (
                sum(1 for a, b in zip(iinfo[k], oinfo[k]) if a != b) + abs(len(iinfo[k]) - len(oinfo[k])),
                len(iinfo[k]), len(oinfo[k])))
    if collections.Counter(iinfo["refs"]) != collections.Counter(oinfo["refs"]):
        miss = collections.Counter(iinfo["refs"]) - collections.Counter(oinfo["refs"])
        add = collections.Counter(oinfo["refs"]) - collections.Counter(iinfo["refs"])
        P.add("compare-refs", "$", "%d removed / %d added reference strings" % (sum(miss.values()), sum(add.values())))
    # per-entry key paths, keyed by entry position (resource count compared above)
    ie = inp.get("entry") or [] if isinstance(inp, dict) else []
    oe = out.get("entry") or [] if isinstance(out, dict) else []
    pairs = [("$", {k: v for k, v in inp.items() if k != "entry"}, {k: v for k, v in out.items() if k != "entry"})]
    for i, (a, b) in enumerate(zip(ie, oe)):
        pairs.append(("$.entry[%d]" % i, a, b))
    for base, a, b in pairs:
        ka, kb = key_paths(a), key_paths(b)
        for p in sorted(set(ka) - set(kb)):
            leaf = p.rsplit(".", 1)[-1]
            if leaf in DECLARED_REMOVALS or any(seg.lstrip(".").split("[")[0] in DECLARED_REMOVALS
                                                for seg in re.findall(r"\.[^.]+", p)):
                continue
            P.add("compare-removed-path", base + p, "key path missing in output")
        for p in sorted(set(kb) - set(ka)):
            P.add("compare-added-path", base + p, "key path not in input")
        for p in sorted(set(ka) & set(kb)):
            if ka[p] != kb[p] and not kb[p] <= ka[p]:
                P.add("compare-type", base + p, "value type %s -> %s" % ("/".join(sorted(ka[p])),
                                                                         "/".join(sorted(kb[p]))))


# ----------------------------------------------------------------------------- driver

def load(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def is_fhir(data: Any) -> bool:
    return isinstance(data, dict) and data.get("resourceType") == "Bundle"


def files_under(root: Path) -> List[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".fhir", ""))


def find_input(rel: Path, name: str, cmp_root: Path) -> Optional[Path]:
    if cmp_root.is_file():
        return cmp_root
    c = cmp_root / rel
    if c.is_file():
        return c
    hits = list(cmp_root.rglob(name))
    return hits[0] if len(hits) == 1 else None


def check_file(path: Path, cmp_path: Optional[Path] = None) -> Tuple[Problems, Problems]:
    """Returns (problems of this file, problems also present in the input = inherited)."""
    data, err = load(path)
    P = Problems()
    if err:
        P.add("parse", "$", "not JSON (%s)" % err)
        return P, Problems()
    P, info = check_bundle(data)
    inherited = Problems()
    if cmp_path is not None:
        idata, ierr = load(cmp_path)
        if ierr:
            P.add("compare-input", "$", "input not readable")
        else:
            IP, iinfo = check_bundle(idata)
            base = {(k, p) for k, p, _ in IP.items}
            keep = Problems()
            for k, p, d in P.items:
                (inherited if (k, p) in base else keep).items.append((k, p, d))
            P = keep
            compare(idata, data, iinfo, info, P)
    return P, inherited


def main(argv: List[str]) -> int:
    args = [a for a in argv if a not in ("-v", "--verbose")]
    verbose = len(args) != len(argv)
    show_names = "--names" in args      # file names are printed only on request; the default is an opaque handle
    args = [a for a in args if a != "--names"]
    cmp_root = None
    if "--compare" in args:
        i = args.index("--compare")
        cmp_root = Path(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 0
    root = Path(args[0])
    total = collections.Counter()  # type: collections.Counter
    inh_total = collections.Counter()  # type: collections.Counter
    n = 0
    for f in files_under(root):
        data, err = load(f)
        if err is None and not is_fhir(data):
            continue
        n += 1
        cp = None
        if cmp_root is not None:
            rel = f.relative_to(root) if root.is_dir() else Path(f.name)
            cp = find_input(rel, f.name, cmp_root)
        P, inh = check_file(f, cp)
        c = P.counts()
        total.update(c)
        inh_total.update(inh.counts())
        label = f.relative_to(root) if root.is_dir() else f.name
        if not show_names:                 # a file name can hold personal data when the input side is checked
            label = "bundle-" + hashlib.sha256(str(label).encode("utf-8", "replace")).hexdigest()[:8]
        extra = "" if cmp_root is None or cp is not None else " (no input to compare)"
        print("%s: %d problem(s)%s %s" % (label, len(P.items), extra,
                                        " ".join("%s=%d" % kv for kv in sorted(c.items()))))
        if verbose:
            for k, p, d in P.items:
                print("    [%s] %s  %s" % (k, p, d))
    print("TOTAL: %d bundle(s), %d problem(s) %s" % (n, sum(total.values()),
                                                     " ".join("%s=%d" % kv for kv in sorted(total.items()))))
    if inh_total:
        print("inherited from input (not counted): %s" % " ".join("%s=%d" % kv for kv in sorted(inh_total.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
