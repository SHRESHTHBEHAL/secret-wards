"""Record layouts, record boundaries and cannot-link rules for structured files (invented data)."""
from __future__ import annotations

import unittest

from raksha import fields as F
from raksha import harvest
from raksha.link import link
from raksha.types import KIND_CSV, KIND_FHIR, KIND_JSON, KIND_TEXT, ParsedFile, Record


def _csv(header, rows, rel="x/a.csv"):
    return ParsedFile(rel=rel, sha256="a" * 64, kind=KIND_CSV, header=list(header), rows=[list(r) for r in rows])


def _json(data, rel="x/a.json"):
    return ParsedFile(rel=rel, sha256="b" * 64, kind=KIND_JSON, data=data)


class CsvLayout(unittest.TestCase):
    def test_headerless_first_line_is_row0(self):
        pf = _csv(["QX-55120-A", "Ravindra Pokharkar", "44/M", "98111 22334", "2026/02/03"],
                  [["QX-55140-B", "Suvarna Tidke", "39/F", "97222 33445", "2026/02/04"],
                   ["QX-55160-C", "Dhanraj Ukey", "61/M", "96333 44556", "2026/02/05"]])
        labels, rows, hl = harvest.csv_view(pf)
        self.assertEqual(hl, 0)
        self.assertEqual(len(rows), 3)
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1", "row:2"])
        self.assertIn("phone:9811122334", recs[0].facts.ids)

    def test_id_name_header_is_still_a_header(self):
        pf = _csv(["time", "QX-0011223 Ravi", "QX-0011224 Mina"], [["06:00", "120/80", "118/76"]])
        self.assertEqual(harvest.csv_view(pf)[2], 1)

    def test_two_header_rows(self):
        pf = _csv(["", "Contact", "", "Patient", ""],
                  [["", "Mob", "Alt", "Name of Pt.", "Yrs"],
                   ["QX/2026/IP/1001", "98111 22334", "", "Ravindra Pokharkar", "44"],
                   ["QX/2026/IP/1002", "97222 33445", "", "Suvarna Tidke", "39"]])
        labels, rows, hl = harvest.csv_view(pf)
        self.assertEqual(hl, 2)
        self.assertEqual(labels[1], "Mob")
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1"])
        self.assertEqual(recs[0].facts.names, ["Ravindra Pokharkar"])


class JsonBoundaries(unittest.TestCase):
    def test_index_keyed_by_mobile_and_name(self):
        data = {"byMobile": {"9811122334": {"last": "2026-02-02"}, "97222-33445": {"last": "2026-02-03"}},
                "byName": {"Ravindra Pokharkar": {"visits": 2}, "Suvarna Tidke": {"visits": 1}},
                "attendant: Mina Ukey (9633 344 556)": {"pass": "GP-00999"}}
        recs = harvest.harvest_file(_json(data))
        locs = [r.loc for r in recs]
        self.assertEqual(locs, ["/byMobile/9811122334", "/byMobile/97222-33445",
                                "/byName/Ravindra Pokharkar", "/byName/Suvarna Tidke"])
        self.assertEqual(recs[1].facts.ids, ["phone:9722233445"])
        mapping, _ = link(recs)
        vals = [mapping[(r.rel, r.loc)] for r in recs]
        self.assertEqual(len({v for v in vals if v}), len([v for v in vals if v]))   # nobody merged

    def test_ticket_array_is_a_record_list(self):
        data = {"tickets": [{"id": "T-1", "raisedBy": "Ravindra Pokharkar", "cb": "98111 22334", "msg": "x"},
                            {"id": "T-2", "raisedBy": "Suvarna Tidke", "cb": "97222 33445", "msg": "y"}]}
        self.assertEqual([r.loc for r in harvest.harvest_file(_json(data))], ["/tickets/0", "/tickets/1"])

    def test_fhir_collection_of_two_patients(self):
        def pat(u, name, ph, dob, g):
            return {"fullUrl": u, "resource": {"resourceType": "Patient", "name": [{"text": name}],
                                               "telecom": [{"system": "phone", "value": ph}],
                                               "birthDate": dob, "gender": g}}
        data = {"resourceType": "Bundle", "type": "collection", "entry": [
            pat("urn:uuid:p1", "Mina Ukey", "9811122334", "1975-03-02", "female"),
            {"fullUrl": "urn:uuid:o1", "resource": {"resourceType": "Observation", "subject": {"reference": "urn:uuid:p1"}}},
            pat("urn:uuid:p2", "Dhanraj Ukey", "9811122334", "1971-08-19", "male"),
            {"fullUrl": "urn:uuid:o2", "resource": {"resourceType": "Observation", "subject": {"reference": "urn:uuid:p2"}}}]}
        pf = ParsedFile(rel="x/b.json", sha256="c" * 64, kind=KIND_FHIR, data=data)
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["/entry/0", "/entry/1", "/entry/2", "/entry/3"])
        mapping, _ = link(recs)
        m = [mapping[(r.rel, r.loc)] for r in recs]
        self.assertEqual(m[0], m[1])
        self.assertEqual(m[2], m[3])
        self.assertNotEqual(m[0], m[2])      # shared family phone never merges


class MultiPatientText(unittest.TestCase):
    def test_census_table_links_nobody(self):
        text = ("WARD CENSUS\nBed | Name | Age/Sex | Attendant / Ph\n"
                " 1 | Ravi K. | 49/M | wife Lata 9811122334\n"
                " 2 | Mohan Das | 63/M | son 97222 33445\n"
                " 3 | Anil | 55/M | wife Rekha\n")
        recs = harvest.harvest_file(ParsedFile(rel="t/c.txt", sha256="d" * 64, kind=KIND_TEXT, text=text))
        self.assertFalse(recs[0].facts.is_patient)
        self.assertEqual(recs[0].facts.ids, [])


class LabelStems(unittest.TestCase):
    def test_government_ids(self):
        for lb in ("Voter ID", "EPIC No", "Ration Card", "DL No", "Passport"):
            self.assertEqual(F.classify_label(lb), F.PAN, lb)

    def test_reference_numbers_kept(self):
        for lb in ("Sample No", "Batch", "Token", "Bill No", "UTR No", "Bank Ref", "Call ID", "Machine", "preauthNo"):
            self.assertEqual(F.classify_label(lb), F.OTHER_ID, lb)

    def test_locality_and_relative_stems(self):
        self.assertEqual(F.classify_label("Para/Leikai"), F.LOCALITY)
        self.assertEqual(F.classify_label("Fthr/Hsbnd"), F.RELATIVE)
        self.assertEqual(F.classify_label("Pt Nm"), F.NAME)


class LinkRules(unittest.TestCase):
    def test_prefixed_hospital_number(self):
        a = harvest.harvest_file(_csv(["Hosp No", "Name", "Age"], [["4471777", "Ravindra Pokharkar", "44"]], "r/a.csv"))
        b = harvest.harvest_file(_csv(["Reg No", "Patient Name", "Age"], [["QXH-4471777", "POKHARKAR RAVINDRA", "44"]], "r/b.csv"))
        mapping, _ = link(a + b)
        self.assertIsNotNone(mapping[("r/a.csv", "row:0")])
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("r/b.csv", "row:0")])


if __name__ == "__main__":
    unittest.main()
