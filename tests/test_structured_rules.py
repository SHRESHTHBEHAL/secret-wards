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


import datetime as _dt

from raksha.link import names_compatible
from raksha.types import Facts


def _R(rel, loc, **kw):
    return Record(rel=rel, loc=loc, facts=Facts(**kw))


class NameCompatibility(unittest.TestCase):
    def test_initials_joined_tokens_any_order(self):
        self.assertTrue(names_compatible("Velamuri Kanaka Ramarao", "V. K. Rama Rao"))
        self.assertTrue(names_compatible("TORVALE K RAMARAO", "Torvale Kanaka Ramarao"))
        self.assertTrue(names_compatible("Dolma C. Tsherpa", "Dolma Chimi Tsherpa"))
        self.assertTrue(names_compatible("Velmuri's wife Ponnamma", "Ponnamma"))
        self.assertTrue(names_compatible("Velankamma", "Velangamma"))   # nasal + voiced / voiceless stop

    def test_incompatible(self):
        self.assertFalse(names_compatible("Ravesh Kumar", "Suvesh Kumar"))
        self.assertFalse(names_compatible("A Kumar", "Anvit Tarle"))   # an initial alone is not enough
        self.assertFalse(names_compatible("Anvit", "Sunil Q"))


class LinkRulesNew(unittest.TestCase):
    def test_phone_with_initials_name_links(self):
        m, _ = link([
            _R("a.csv", "row:0", names=["Torvale Kanaka Ramarao"], ids=["uhid:3301958", "phone:9000011111"]),
            _R("b.csv", "row:0", names=["T. K. Rama Rao"], ids=["phone:9000011111"], age=61),
        ])
        self.assertIsNotNone(m[("a.csv", "row:0")])
        self.assertEqual(m[("a.csv", "row:0")], m[("b.csv", "row:0")])

    def test_family_phone_different_given_name_refused(self):
        m, _ = link([
            _R("a.csv", "row:0", names=["Ravesh Tarle"], ids=["uhid:Q1001", "phone:9000022222"]),
            _R("a.csv", "row:1", names=["Suvesh Tarle"], ids=["uhid:Q1002", "phone:9000022222"]),
        ])
        self.assertNotEqual(m[("a.csv", "row:0")], m[("a.csv", "row:1")])

    def test_hospital_id_with_and_without_prefix_unnamed_side(self):
        m, _ = link([
            _R("reg.csv", "row:0", names=["Velu Parkar"], ids=["uhid:4472999"]),
            _R("opd.json", "/e/0", relatives=[("brother", "Kanu Parkar")], ids=["uhid:QMH4472999"]),
        ])
        self.assertEqual(m[("reg.csv", "row:0")], m[("opd.json", "/e/0")])

    def test_year_segment_and_suffix_need_compatible_names(self):
        m, _ = link([
            _R("a.json", "/p/0", names=["Lanu Ozuk"], ids=["uhid:QN202600417K"]),
            _R("b.csv", "row:0", names=["Lanu Ozuk"], ids=["uhid:QN0417"]),
            _R("c.csv", "row:0", names=["Temsu Imcha"], ids=["uhid:QN00417"]),
        ])
        self.assertEqual(m[("a.json", "/p/0")], m[("b.csv", "row:0")])
        self.assertNotEqual(m[("a.json", "/p/0")], m[("c.csv", "row:0")])

    def test_satellite_joins_only_with_compatible_name(self):
        recs = [
            _R("reg.csv", "row:0", names=["Hirav Kolvate"], ids=["uhid:Z7001", "phone:9000033333"], age=40),
            _R("sales.csv", "row:0", names=["Hirav Kolvate"], ids=["phone:9000033333"], is_patient=False),
            _R("sales.csv", "row:1", names=["Minal Kolvate"], ids=["phone:9000033333"], is_patient=False),
            _R("sales.csv", "row:2", names=["Prabin Sau"], ids=["phone:9000044444"], is_patient=False),
        ]
        m, _ = link(recs)
        self.assertEqual(m[("reg.csv", "row:0")], m[("sales.csv", "row:0")])
        self.assertIsNone(m[("sales.csv", "row:2")])
        self.assertNotEqual(m[("reg.csv", "row:0")], m[("sales.csv", "row:1")])

    def test_family_phone_patronymic_middle_name(self):
        d = _dt.date
        m, _ = link([
            _R("reg.csv", "row:0", names=["Vasant Ghorpale"], relatives=[("Pita", "Bhimrao Ghorpale")],
               ids=["aadhaar:111122223333", "phone:9000055555"], dob=d(1960, 1, 2)),
            _R("reg.csv", "row:1", names=["Malati Vasant Ghorpale"], ids=["aadhaar:444455556666", "phone:9000055555"],
               dob=d(1966, 3, 4)),
            _R("tpa.json", "/r/0", names=["GHORPALE VASANT BHIMRAO"], ids=["abha:12345678901234", "phone:9000055555"]),
        ])
        self.assertEqual(m[("reg.csv", "row:0")], m[("tpa.json", "/r/0")])
        self.assertNotEqual(m[("reg.csv", "row:1")], m[("tpa.json", "/r/0")])

    def test_same_full_name_same_date(self):
        d = _dt.date(2026, 2, 19)
        m, _ = link([
            _R("reg.csv", "row:0", names=["Kotresh Halmani"], ids=["uhid:5550001"], ref_date=d),
            _R("claims.csv", "row:0", names=["Halmani Kotresh"], ids=["ins:QQ00077"], ref_date=d),
            _R("claims.csv", "row:1", names=["Halmani Kotresh"], ids=["ins:QQ00078"], ref_date=_dt.date(2026, 3, 1)),
        ])
        self.assertEqual(m[("reg.csv", "row:0")], m[("claims.csv", "row:0")])
        self.assertNotEqual(m[("reg.csv", "row:0")], m[("claims.csv", "row:1")])

    def test_nameless_doc_relative_and_age(self):
        m, _ = link([
            _R("death.txt", "doc", names=["Rasool Bhat"], relatives=[("", "Imtiyaz")], ids=["uhid:SQ1177"], age=66),
            _R("ref.txt", "doc", relatives=[("son", "Imtiyaz Ahmad")], ids=["phone:9000066666"], age=66),
            _R("other.txt", "doc", relatives=[("son", "Imtiyaz Ahmad")], ids=["phone:9000077777"], age=40),
        ])
        self.assertEqual(m[("death.txt", "doc")], m[("ref.txt", "doc")])
        self.assertNotEqual(m[("death.txt", "doc")], m[("other.txt", "doc")])


class MetadataAndHeaders(unittest.TestCase):
    def test_export_metadata_person(self):
        self.assertEqual(F.json_key_type(["_exportInfo", "printedFor"], "Abc Defgh (9000 111 222)"), F.NAME)
        self.assertNotEqual(F.json_key_type(["_exportInfo", "exportedBy"], "clerk07"), F.NAME)

    def test_measurement_is_not_an_id(self):
        self.assertEqual(F.json_key_type(["cbc", "tlc"], "TLC 13400 /cumm"), F.CLINICAL)
        self.assertEqual(F.json_key_type(["pt", "n"], "Dolma C. Tsherpa"), F.NAME)

    def test_header_sentence_makes_rows_one_patient(self):
        recs = harvest.harvest_file(_csv(["Chart: Mr Velu Parkar (IP 26/7781-QX) Ph 9000 888 777", "BP"],
                                         [["01-Jan-2026", "120/80"], ["02-Jan-2026", "118/76"]]))
        m, _ = link(recs)
        self.assertIsNotNone(m[("x/a.csv", "row:0")])
        self.assertEqual(m[("x/a.csv", "row:0")], m[("x/a.csv", "row:1")])

    def test_file_name_person_is_not_content_evidence(self):
        data = {"pt": {"n": "Dolma C. Tsherpa", "m": "90000-12345", "age": 40}, "cbc": {"hb": "Hb 10.9 g/dL"}}
        f = harvest.harvest_file(_json(data, rel="lab/Anvit_Rao_Tarle_9000099999_cbc.json"))[0].facts
        self.assertTrue(f.is_patient)
        self.assertIn("phone:9000012345", f.ids)
        self.assertNotIn("phone:9000099999", f.ids)


class InstitutionAndReferenceRules(unittest.TestCase):
    def test_institution_named_after_person_is_hospital(self):
        from raksha import fields as F
        self.assertEqual(F.classify_column("Hosp", ["Aaaa Bbbb Memorial Hospital", "Cccc Trust Hospital"]),
                         F.HOSPITAL)
        self.assertEqual(F.json_key_type(["tpa"], "Dddd Health TPA"), F.HOSPITAL)
        self.assertEqual(F.json_key_type(["site", "name"], "Eeee Ffff Block Microbiology"), F.HOSPITAL)
        self.assertFalse(F.is_institution("Gggg Block"))

    def test_reference_columns_are_other_ids(self):
        from raksha import fields as F
        for label in ("Sample No", "Batch", "Call ID", "Vehicle", "Pre-Auth No", "encId", "visitId",
                      "episode", "gatePass"):
            self.assertEqual(F.classify_label(label), F.OTHER_ID, label)
        for label in ("Odo (km)", "MRP", "Estimate", "roomRentPerDay", "Access"):
            self.assertEqual(F.classify_label(label), F.CLINICAL, label)
        self.assertEqual(F.classify_label("IPD No"), F.ENC_ID)

    def test_eponym_score_is_not_a_name(self):
        from raksha import fields as F
        self.assertNotEqual(F._value_shape("Hhhh Coma Scale"), F.NAME)

    def test_unlabelled_relative_and_village_columns(self):
        from raksha import fields as F
        cols = [["S/o Aaaa Bbbb", "W/o Cccc Dddd"], ["Eeeevillage", "Ffffpur"], ["Gggg", "Hhhh"],
                ["400001", "500002"]]
        out = F.refine_unlabelled(["", "", "", ""], [F.OTHER, F.OTHER, F.OTHER, F.PIN], cols)
        self.assertEqual(out[0], F.RELATIVE)
        self.assertEqual(out[1], F.VILLAGE)
        self.assertEqual(out[2], F.OTHER)

    def test_kin_phrase_tail(self):
        from raksha.sanitize import _KIN_TAIL
        out = _KIN_TAIL.sub(lambda m: m.group(1) + "[RELATIVE]", "[NAME] ke parijan Iiii Jjjj: shift kiya")
        self.assertNotIn("Iiii", out)
