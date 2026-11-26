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

    def test_header_sentence_does_not_attribute_bare_rows(self):
        # organisers' convention: a chart row with no identity evidence of its own has no patient
        recs = harvest.harvest_file(_csv(["Chart: Mr Velu Parkar (IP 26/7781-QX) Ph 9000 888 777", "BP"],
                                         [["01-Jan-2026", "120/80"], ["02-Jan-2026", "118/76"]]))
        m, _ = link(recs)
        self.assertIsNone(m[("x/a.csv", "row:0")])
        self.assertIsNone(m[("x/a.csv", "row:1")])

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


class HeaderlessDetectionTest(unittest.TestCase):
    """Line 1 is data when its cell shapes agree with the columns under it (invented values)."""

    def _view(self, header, rows):
        return harvest.csv_view(ParsedFile(rel="m/h.csv", sha256="d" * 64, kind=KIND_CSV,
                                           header=list(header), rows=[list(r) for r in rows]))

    def test_headerless_mixed_ids(self):
        rows = [["2025-03-04", "QX-77-1234567", "Tavi Rumen", "41", "M", "9123456780", "fever"],
                ["2025-03-05", "ZRT-12-883311", "Oma Kesh", "35", "F", "9988776655", "cough"],
                ["2025-03-06", "QQ-9-11-2233", "Lio Vant", "52", "M", "9012345678", "rash"]]
        labels, data, hl = self._view(rows[0], rows[1:])
        self.assertEqual(hl, 0)
        self.assertEqual(len(data), 3)

    def test_real_header_kept(self):
        header = ["Reg_No", "Visit Date", "Patient Name", "Age", "Sex", "Mobile", "Complaint"]
        rows = [["QX1234567", "2025-03-04", "Tavi Rumen", "41", "M", "9123456780", "fever"]]
        self.assertEqual(self._view(header, rows)[2], 1)

    def test_unnamed_index_column_header(self):
        header = ["", "uhid", "name", "phone"]
        rows = [["0", "QX1234567", "Tavi Rumen", "9123456780"], ["1", "QX1234568", "Oma Kesh", "9988776655"]]
        self.assertEqual(self._view(header, rows)[2], 1)

    def test_one_and_two_row_headerless(self):
        one = ["2025-03-04", "QX1234567", "Tavi Rumen", "9123456780"]
        self.assertEqual(self._view(one, [])[2], 0)
        self.assertEqual(self._view(one, [["2025-03-05", "QX1234568", "Oma Kesh", "9988776655"]])[2], 0)

    def test_title_line_above_header(self):
        header = ["Ward register 2025", "", "", ""]
        rows = [["UHID", "Patient Name", "Mobile", "Age"], ["QX1234567", "Tavi Rumen", "9123456780", "41"],
                ["QX1234568", "Oma Kesh", "9988776655", "35"]]
        labels, data, hl = self._view(header, rows)
        self.assertEqual(hl, 2)
        self.assertEqual(len(data), 2)

    def test_barcode_column_not_phone(self):
        self.assertEqual(F.classify_column("barcode", ["8123400593", "8123400594"]), F.OTHER_ID)
        self.assertEqual(F.classify_column("Mobile", ["8123400593", "8123400594"]), F.PHONE)

    def test_document_number_keys_keep_locators(self):
        self.assertEqual(harvest.key_kind("LAB-2025-000123"), "doc")
        self.assertEqual(harvest.keyed_record_id("/LAB-2025-000123"), "")


class RoundFresh2Rules(unittest.TestCase):
    """Invented data: pipe files, title-line charts, reference columns, address cells."""

    def test_psv_is_pipe_delimited(self):
        import tempfile
        from pathlib import Path
        from raksha import ingest
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chart.psv"
            p.write_text("Time|Temp|Pulse\n06:00|98.6|72\n10:00|99.1|80\n", encoding="utf-8")
            pf = ingest.load(p, Path(d))
        self.assertEqual(pf.kind, KIND_CSV)
        self.assertEqual(pf.delimiter, "|")
        self.assertEqual(len(pf.rows), 2)

    def test_title_patient_only_on_rows_with_own_evidence(self):
        pf = _csv(["Time", "Temp", "BP", "Remarks", "Chart for patient - Ovrin Talpade QRH/2031/004417"],
                  [["06:00", "98.6", "120/80", "stable", ""],
                   ["10:00", "99.1", "118/76", "NOK Mitul Talpade 9123456780", ""]])
        recs = harvest.harvest_file(pf)
        self.assertEqual(recs[0].facts.ids, [])
        self.assertTrue(set(recs[0].facts.names) <= set(getattr(recs[0].facts, "link_skip", [])))
        self.assertIsNone(link(recs)[0][("x/a.csv", "row:0")])
        f1 = recs[1].facts
        self.assertTrue(any(t.startswith("phone:") for t in f1.ids))
        self.assertTrue(any(t.startswith("uhid:") for t in f1.ids))

    def test_reference_object_columns(self):
        vals = ["QX-31-4471", "QX-31-4502", "QX-31-4518"]
        for label in ("Bag No", "Issue No", "Slide No", "Requisition No", "Indent No", "Challan No",
                      "Segment No", "Cartridge No"):
            self.assertEqual(F.classify_column(label, vals), F.OTHER_ID, label)
        self.assertEqual(F.classify_column("Hosp No", vals), F.PATIENT_ID)

    def test_address_cell_drops_pin_and_door_number(self):
        import csv as _csv_mod
        import io
        from raksha.policy import DEFAULTS
        from raksha.pseudo import Keys
        from raksha.sanitize import Env, sanitize_file
        from raksha.types import Patient
        pf = ParsedFile(rel="r/reg.csv", sha256="c" * 64, kind=KIND_CSV, delimiter=",",
                        header=["Reg No", "Pt Name", "Address"],
                        rows=[["QRH-2077123", "Ovrin Talpade", "71-4-903/2, Kesarbagh Lane, Hyderabad 509871"]])
        facts = harvest.harvest_file(pf)[0].facts
        env = Env(keys=Keys(b"unit-secret"), assign={(pf.rel, "row:0"): "k1"},
                  book={"k1": Patient(key="k1", records=[(pf.rel, "row:0")], facts=[facts])},
                  policy=dict(DEFAULTS), pseudonyms={"k1": "PSN-TESTAAAAAA"},
                  records={pf.rel: [Record(rel=pf.rel, loc="row:0", facts=facts)]})
        out = sanitize_file(pf, env).content
        cell = list(_csv_mod.reader(io.StringIO(out)))[1][2]
        self.assertNotIn("509871", cell)
        self.assertNotIn("71-4-903", cell)
        self.assertNotIn("Kesarbagh", cell)


class HandoverAndPlaceColumns(unittest.TestCase):
    def test_handover_labels_are_people(self):
        from raksha import fields as F
        for label in ("Issued To", "Given To", "Handed To", "Received By", "Collected By", "Witness",
                      "Informant", "Witness Name", "issued_to", "receivedBy"):
            self.assertEqual(F.classify_label(label), F.RELATIVE, label)
        for label in ("Issued On", "Issue Date", "Collected On", "Received On"):
            self.assertEqual(F.classify_label(label), F.DATE, label)

    def test_pickup_point_is_locality(self):
        from raksha import fields as F
        self.assertEqual(F.classify_label("Pickup_point"), F.LOCALITY)

    def test_place_before_district_column(self):
        from raksha import fields as F
        cols = [["Qqqq Ward", "Rrrr Nagar, B Lane", "Ssss Tttt"], ["Pune", "Nagpur", "Thane"]]
        out = F.refine_unlabelled(["", ""], [F.OTHER, F.OTHER], cols)
        self.assertEqual(out[0], F.VILLAGE)
        self.assertEqual(out[1], F.OTHER)     # the district keeps its type (district policy unchanged)

    def test_address_parent_key_is_place(self):
        from raksha import fields as F
        self.assertEqual(F.json_key_type(["cases", "residence", "at_post"], "Uuuu Khurd"), F.VILLAGE)
        self.assertEqual(F.json_key_type(["cases", "residence", "gaon"], "Vvvv"), F.VILLAGE)

    def test_town_column_of_districts_is_district(self):
        from raksha import fields as F
        self.assertEqual(F.classify_column("TOWN", ["Pune", "Nagpur", "Thane", "Nashik"]), F.DISTRICT)
        self.assertEqual(F.classify_column("TOWN", ["Wwww", "Xxxxpur", "Pune"]), F.VILLAGE)


class HindiKeyVisitsAndGuards(unittest.TestCase):
    """Invented data: transliterated-Hindi visit lists, export headers, quantity values, guards."""

    def _slips(self):
        return {"niryat": {"application": "Sehat Kosh", "facility": "Dhanpur Zila Chikitsalaya",
                           "sampark_sahayata": "Helpdesk 9811100223"},
                "parchiyan": [
                    {"parchi_kramank": "OPD-1101", "mareez_sandarbh": "DZC.P.700101", "dinank": "02.03.2026",
                     "dawaiyan": [{"dawa": "Tab Paracetamol", "matra": "500 mg"}],
                     "tippani": "Gomti ke pita saath aaye."},
                    {"parchi_kramank": "OPD-1102", "mareez_sandarbh": "DZC.P.700202", "dinank": "03.03.2026",
                     "dawaiyan": [{"dawa": "Inj IVIG", "matra": "0.4 g/kg"}], "tippani": "Follow up."}]}

    def test_hindi_keyed_visit_list_splits_per_entry(self):
        recs = harvest.harvest_file(_json(self._slips()))
        self.assertEqual([r.loc for r in recs], ["/parchiyan/0", "/parchiyan/1"])
        self.assertEqual(recs[0].facts.ids, ["uhid:DZCP700101"])
        self.assertNotIn("phone:9811100223", recs[0].facts.ids + recs[1].facts.ids)
        mapping, _ = link(recs)
        self.assertNotEqual(mapping[(recs[0].rel, recs[0].loc)], mapping[(recs[1].rel, recs[1].loc)])

    def test_key_types(self):
        self.assertEqual(F.json_key_type(["parchiyan", "mareez_sandarbh"], "DZC.P.700101"), F.PATIENT_ID)
        self.assertEqual(F.json_key_type(["dawaiyan", "matra"], "500 mg"), F.CLINICAL)
        self.assertEqual(F.json_key_type(["meta", "application"], "Sehat Kosh"), F.OTHER)
        self.assertEqual(F.json_key_type(["rows", "vid"], "ab12cd34"), F.OTHER_ID)
        # a quantity with a unit is never a place, whatever the key
        self.assertEqual(F.json_key_type(["addr", "gaon"], "4 g"), F.CLINICAL)
        self.assertEqual(F.json_key_type(["addr", "gaon"], "Kesarpur"), F.VILLAGE)

    def test_transliterated_institutions(self):
        for v in ("Dhanpur Lokseva Rugnalaya", "Dhanpur Zila Chikitsalaya", "Hriday Rog Vibhag",
                  "Shishu Gahan Ikai", "Cardio Step-down", "Isolation Bay"):
            self.assertTrue(F.is_institution(v), v)
        self.assertFalse(F.is_institution("Kamla Devi"))

    def test_kinship_word_longest_match(self):
        self.assertEqual(harvest.split_relative("पुत्री रामेश्वर"), ("पुत्री", "रामेश्वर"))
        self.assertEqual(harvest.split_relative("पुत्र रामेश्वर"), ("पुत्र", "रामेश्वर"))

    def test_header_id_does_not_merge_visits_of_different_patients(self):
        data = {"exportHeader": {"facility": "Dhanpur Mission Hospital", "requestedFor": "DMH26A10001"},
                "opVisits": [{"hospNoRef": "DMH26A10001", "dateOfVisit": "01.02.2026"},
                             {"hospNoRef": "DMH26A20002", "dateOfVisit": "02.02.2026"}]}
        recs = harvest.harvest_file(_json(data))
        self.assertEqual([r.loc for r in recs], ["/opVisits/0", "/opVisits/1"])

    def test_old_unlabelled_date_is_not_an_event_date(self):
        import datetime as dt
        from raksha.types import Facts
        reg = Facts(names=["Kesari Wankhede"], ids=["uhid:QXH55001", "aadhaar:556677889900"],
                    dob=dt.date(1980, 5, 6), gender="F")
        note = Facts(names=["Kesari Wankhede"], ids=["uhid:QXH55001"], age=45, gender="F",
                     ref_date=dt.date(1980, 5, 6))
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="d/b.txt", loc="doc", facts=note)]
        mapping, _ = link(recs)
        self.assertIsNotNone(mapping[("r/a.csv", "row:0")])
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("d/b.txt", "doc")])

    def test_country_code_phone_is_not_an_aadhaar_conflict(self):
        from raksha.types import Facts
        reg = Facts(names=["Lanu Ao"], ids=["uhid:QXH66001", "aadhaar:334455667788", "phone:9876501234"])
        note = Facts(names=["Lanu Ao"], ids=["uhid:QXH66001", "aadhaar:919876501234", "phone:9876501234"])
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="d/b.txt", loc="doc", facts=note)]
        mapping, _ = link(recs)
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("d/b.txt", "doc")])

    def test_real_aadhaar_conflict_still_blocks(self):
        from raksha.types import Facts
        a = Facts(names=["Lanu Ao"], ids=["uhid:QXH66001", "aadhaar:334455667788"])
        b = Facts(names=["Lanu Ao"], ids=["uhid:QXH66001", "aadhaar:998877665544"])
        recs = [Record(rel="r/a.csv", loc="row:0", facts=a), Record(rel="d/b.txt", loc="doc", facts=b)]
        mapping, _ = link(recs)
        self.assertNotEqual(mapping[("r/a.csv", "row:0")], mapping[("d/b.txt", "doc")])


class LinkRecallRules(unittest.TestCase):
    def test_country_code_mobile_aadhaar_without_own_phone_does_not_conflict(self):
        reg = Facts(names=["Temjen Longkumer"], ids=["uhid:QZK77001", "aadhaar:445566778899", "phone:9876512345"])
        slip = Facts(names=["Temjen Longkumer"], ids=["uhid:QZK77001", "aadhaar:919876512345"])
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="p/s.txt", loc="doc", facts=slip)]
        mapping, _ = link(recs)
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("p/s.txt", "doc")])

    def test_unlabelled_birth_date_in_text_gives_birth_year(self):
        reg = Facts(names=["Hemlata Dhurve"], ids=["uhid:QZK88001", "aadhaar:445566771122"],
                    dob=_dt.date(1991, 3, 4), age=35, gender="F", ref_date=_dt.date(2026, 1, 2))
        other = [Facts(names=["Rupa Kerketta"], ids=["uhid:QZK88%03d" % i], ref_date=_dt.date(2026, 2, i + 1))
                 for i in range(2, 5)]
        note = Facts(names=["Hemlata Dhurve"], ids=["uhid:QZK88001"], age=35, gender="F",
                     ref_date=_dt.date(1991, 3, 4))
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="d/b.txt", loc="doc", facts=note)]
        recs += [Record(rel="r/a.csv", loc="row:%d" % (i + 1), facts=f) for i, f in enumerate(other)]
        mapping, _ = link(recs)
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("d/b.txt", "doc")])

    def test_admission_column_holding_the_hospital_number_links_with_same_name(self):
        reg = Facts(names=["Lalthansanga Pachuau"], ids=["uhid:QZKH4400123"], age=52)
        ot = Facts(names=["Lalthansanga Pachuau"], ids=["enc:QZKH4400123"], age=52)
        stranger = Facts(names=["Imkong Jamir"], ids=["enc:QZKH4400999"])
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="o/ot.csv", loc="row:0", facts=ot),
                Record(rel="o/ot.csv", loc="row:1", facts=stranger)]
        mapping, _ = link(recs)
        self.assertEqual(mapping[("r/a.csv", "row:0")], mapping[("o/ot.csv", "row:0")])
        self.assertNotEqual(mapping[("r/a.csv", "row:0")], mapping[("o/ot.csv", "row:1")])

    def test_admission_number_equal_to_hospital_number_needs_compatible_names(self):
        reg = Facts(names=["Lalthansanga Pachuau"], ids=["uhid:QZKH4400123"])
        ot = Facts(names=["Imkong Jamir"], ids=["enc:QZKH4400123"])
        recs = [Record(rel="r/a.csv", loc="row:0", facts=reg), Record(rel="o/ot.csv", loc="row:0", facts=ot)]
        mapping, _ = link(recs)
        self.assertNotEqual(mapping[("r/a.csv", "row:0")], mapping[("o/ot.csv", "row:0")])

    def test_hamlet_key_is_a_village(self):
        self.assertEqual(F.classify_label("hamlet"), F.VILLAGE)

    def test_emergency_contact_name_is_not_the_patient(self):
        self.assertEqual(F.json_key_type(["contact", "emergency", "name"], "Ngurthanzuali Ralte"), F.RELATIVE)
        self.assertEqual(F.json_key_type(["patient", "name"], "Ngurthanzuali Ralte"), F.NAME)

    def test_state_scheme_card_is_insurance(self):
        self.assertEqual(F.classify_label("karunya_card"), F.INSURANCE)

    def test_file_name_sender_is_no_second_patient(self):
        f = Facts(names=["Akum Imchen"], ids=["uhid:QZK99001"])
        f.link_skip = ["Moasangla Pongen"]
        f.names.append("Moasangla Pongen")
        self.assertFalse(harvest._multi_patient_text("Akum Imchen seen today.", f))

    def test_default_year_prefix_scan_matches_full_scan(self):
        from raksha import dates, sanitize
        filler = "x " * 3000
        for text in ["no date here " * 500, filler + "seen 03/04/2025 then 05/06/2024",
                     "visit 5 March then " + filler + " on 2023-01-09", filler[:4090] + "12/11/2021" + filler]:
            full = next((h.date.year for h in dates.find_dates(text[:200000], "dmy") if h.has_year), None)
            self.assertEqual(sanitize._default_year(text, "dmy"), full)


class RoundFresh4Layouts(unittest.TestCase):
    """Invented data: record level of nested JSON, CSV preambles / footers and text tables."""

    def _text(self, text, rel="x/a.txt"):
        return ParsedFile(rel=rel, sha256="c" * 64, kind=KIND_TEXT, text=text)

    def test_batches_of_visits_split_per_visit(self):
        visit = lambda n, name, ph: {"visit": {"no": "V-%d" % n}, "pt": {
            "ident": {"primary": {"sys": "UHID", "val": "QZ/26/%06d" % n}},
            "demog": {"nm": {"given": name, "family": "Qorvat"}, "contact": ph, "dob": "1980-02-0%d" % (n % 9 + 1)}}}
        data = {"export": {"meta": {"source": "HMIS"}, "batches": [
            {"batchId": "B1", "visits": [visit(1, "Ilvan", "9111122223"), visit(2, "Morra", "9222233334")]},
            {"batchId": "B2", "visits": [visit(3, "Tesk", "9333344445"), visit(4, "Yorin", "9444455556")]}]}}
        locs = harvest.record_locs(_json(data))
        self.assertEqual(locs, ["/export/batches/0/visits/0", "/export/batches/0/visits/1",
                                "/export/batches/1/visits/0", "/export/batches/1/visits/1"])
        recs = harvest.harvest_file(_json(data))
        assign = link(recs)[0]
        self.assertEqual(len({assign[(r.rel, r.loc)] for r in recs}), 4)

    def test_patient_list_with_inner_visits_stays_patient_level(self):
        data = {"patients": [
            {"uhid": "QZ/26/000101", "name": "Ilvan Qorvat", "visits": [{"date": "2026-01-02"}, {"date": "2026-01-09"}]},
            {"uhid": "QZ/26/000102", "name": "Morra Qorvat", "visits": [{"date": "2026-01-03"}, {"date": "2026-01-04"}]}]}
        self.assertEqual(harvest.record_locs(_json(data)), ["/patients/0", "/patients/1"])

    def test_comment_line_above_pipe_header(self):
        pf = _csv(["#QZ-HMIS", "export=OPD", "site=Qorvat Hospital", "rows=2", "helpdesk=0612-2345678"],
                  [["UHID", "PATIENT NAME", "REL", "GUARDIAN", "MOBILE"],
                   ["QZ/26/000201", "Ilvan Qorvat", "S/O", "Darro Qorvat", "9111122223"],
                   ["QZ/26/000202", "Morra Tesk", "D/O", "Yalen Tesk", "9222233334"]])
        labels, rows, hl = harvest.csv_view(pf)
        self.assertEqual((labels[0], len(rows), hl), ("UHID", 2, 2))
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1"])
        self.assertIn("Ilvan Qorvat", recs[0].facts.names)
        self.assertNotIn("Darro Qorvat", recs[0].facts.names)

    def test_title_preamble_and_footer_are_not_records(self):
        pf = _csv(["Qorvat Seva Hospital", "", "", "", ""],
                  [["LIS RESULT EXPORT", "", "", "", ""],
                   ["Run date: 02-01-2026", "", "", "Operator: lab_07", ""],
                   ["", "", "", "", ""],
                   ["LabNo", "UHID", "Patient", "Test", "Result"],
                   ["LB26-0000101", "QZ/26/000301", "Ilvan Qorvat", "Hb", "11.2"],
                   ["LB26-0000102", "QZ/26/000302", "Morra Tesk", "TSH", "3.1"],
                   ["", "", "", "", ""],
                   ["End of report. Rows: 2", "", "", "", ""]])
        labels, rows, hl = harvest.csv_view(pf)
        self.assertEqual((labels[1], len(rows), hl), ("UHID", 2, 5))
        self.assertEqual([r.loc for r in harvest.harvest_file(pf)], ["row:0", "row:1"])

    def test_sparse_last_data_row_is_kept(self):
        pf = _csv(["UHID", "Name", "Phone"], [["QZ/26/000401", "Ilvan Qorvat", "9111122223"],
                                             ["QZ/26/000402", "", ""]])
        self.assertEqual(len(harvest.csv_view(pf)[1]), 2)

    def test_key_value_log_lines_one_record_per_line(self):
        text = ("# Qorvat OPD log  site=QZ\n"
                '2026-01-02T09:10 uhid=QZ/26/000501 name="Ilvan Qorvat" age=41 sex=M ph=9111122223 dr="Dr Pell"\n'
                '2026-01-02T09:30 uhid=QZ/26/000502 name="Morra Tesk" age=36 sex=F ph=9222233334 dr="Dr Pell"\n'
                '2026-01-02T09:50 uhid=QZ/26/000503 name="Yorin Daal" age=58 sex=M ph=9333344445 dr="Dr Pell"\n'
                "# end rows=3\n")
        recs = harvest.harvest_file(self._text(text))
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1", "row:2"])
        self.assertIn("Morra Tesk", recs[1].facts.names)
        assign = link(recs)[0]
        self.assertEqual(len({assign[(r.rel, r.loc)] for r in recs}), 3)

    def test_repeated_label_blocks(self):
        blk = "Name: %s\nUHID: %s\nMobile: %s\nComplaint: fever\n"
        text = "QORVAT OPD SLIPS\n\n" + "\n----\n".join(
            blk % x for x in [("Ilvan Qorvat", "QZ/26/000601", "9111122223"),
                              ("Morra Tesk", "QZ/26/000602", "9222233334"),
                              ("Yorin Daal", "QZ/26/000603", "9333344445")])
        recs = harvest.harvest_file(self._text(text))
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1", "row:2"])

    def test_fixed_width_table(self):
        text = ("QORVAT DAY BOOK\n\n"
                "TKN  UHID           NAME               PHONE\n"
                "---- -------------- ------------------ ------------\n"
                "001  QZ-OP-000701   ILVAN QORVAT       9111122223\n"
                "002  QZ-OP-000702   MORRA TESK         9222233334\n"
                "\nTOTAL TOKENS: 2\n")
        recs = harvest.harvest_file(self._text(text))
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1"])
        self.assertTrue(any(t.startswith("phone:") for t in recs[1].facts.ids))

    def test_repeated_test_blocks_without_person_stay_one_document(self):
        text = "Patient: Ilvan Qorvat  UHID QZ/26/000801\n\n" + "\n\n".join(
            "Test: %s\nResult: %s\nUnit: %s\n" % x for x in [("Hb", "11", "g/dl"), ("TSH", "3", "mIU/L"),
                                                              ("Na", "139", "mmol/L")])
        self.assertEqual([r.loc for r in harvest.harvest_file(self._text(text))], ["doc"])

    def test_text_table_end_to_end_scrubs_every_row(self):
        import json
        import tempfile
        from pathlib import Path
        from raksha import pipeline
        text = ('2026-01-02T09:10 uhid=QZ/26/000901 name="Ilvan Qorvat" age=41 sex=M ph=9111122223\n'
                '2026-01-02T09:30 uhid=QZ/26/000902 name="Morra Tesk" age=36 sex=F ph=9222233334\n'
                '2026-01-02T09:50 uhid=QZ/26/000903 name="Yorin Daal" age=58 sex=M ph=9333344445\n')
        with tempfile.TemporaryDirectory() as d:
            inp, out = Path(d) / "in", Path(d) / "out"
            (inp / "opd").mkdir(parents=True)
            (inp / "opd" / "log.txt").write_text(text, encoding="utf-8")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                pipeline.run(inp, out, b"unit-secret", {})
            body = (out / "sanitized" / "opd" / "log.txt").read_text(encoding="utf-8")
            recs = [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        for v in ("Ilvan", "Morra Tesk", "Yorin", "9111122223", "000902", "9333344445"):
            self.assertNotIn(v, body)
        self.assertEqual(sorted(r["loc"] for r in recs), ["row:0", "row:1", "row:2"])
        self.assertEqual(len({r["patient"] for r in recs}), 3)


class RoundFresh4NotPatientIds(unittest.TestCase):
    """Invented data: values filed as a hospital number that are not one never join patients."""

    def _apart(self, a, b):
        recs = [_R("x/a.csv", "row:0", **a), _R("x/b.csv", "row:0", **b)]
        m = link(recs)[0]
        return m[("x/a.csv", "row:0")] is None or m[("x/a.csv", "row:0")] != m[("x/b.csv", "row:0")]

    def test_ifsc_and_event_numbers_never_link(self):
        for tok in ("uhid:QZBN0001234", "uhid:QZLAB2026000117", "uhid:LB26-0000101", "uhid:CLM-26-000412",
                    "uhid:UTR998877665544", "uhid:IMG20260102WA0007", "uhid:BATCH-2026-0042"):
            self.assertTrue(self._apart({"names": ["Ilvan Qorvat"], "ids": [tok]},
                                        {"names": ["Morra Tesk"], "ids": [tok]}), tok)
            self.assertTrue(self._apart({"names": ["Ilvan Qorvat"], "ids": [tok]}, {"ids": [tok]}), tok)

    def test_scheme_card_links_only_with_compatible_names(self):
        card = "uhid:BSKY-26-1234-56789"
        self.assertTrue(self._apart({"names": ["Ilvan Qorvat"], "ids": [card]},
                                    {"names": ["Morra Qorvat"], "ids": [card]}))
        self.assertTrue(self._apart({"names": ["Ilvan Qorvat"], "ids": [card]}, {"ids": [card]}))
        self.assertTrue(self._apart({"names": ["Ilvan Qorvat"], "ids": ["uhid:RC220011223344"]},
                                    {"ids": ["uhid:RC220011223344"]}))
        self.assertFalse(self._apart({"names": ["Ilvan Qorvat"], "ids": [card]},
                                     {"names": ["Ilvan Qorvat"], "ids": ["ins:BSKY2612345678 9"]}))

    def test_hospital_number_still_links(self):
        self.assertFalse(self._apart({"names": ["Ilvan Qorvat"], "ids": ["uhid:QZH/26/004512"]},
                                     {"ids": ["uhid:QZH-26-004512"]}))

    def test_combined_id_proof_cell_typed_by_its_word(self):
        a = {"names": ["Ilvan Qorvat"], "ids": ["pan:AADHAAR 2345-6789-0123"]}
        self.assertFalse(self._apart(a, {"names": ["Ilvan Qorvat"], "ids": ["aadhaar:234567890123"]}))
        masked = {"names": ["Ilvan Qorvat"], "ids": ["pan:AADHAAR XXXXXXXX0123"]}
        self.assertTrue(self._apart(masked, {"names": ["Morra Tesk"], "ids": ["pan:AADHAAR XXXXXXXX0123"]}))
        self.assertTrue(self._apart(masked, {"ids": ["pan:AADHAAR XXXXXXXX0123"]}))


class RoundFresh4Columnar(unittest.TestCase):
    """Invented data: column-oriented JSON (a columns list + an array of row arrays)."""

    def test_columns_and_data_arrays_one_record_per_row(self):
        data = {"sheet": "front desk", "columns": ["uhid", "full_name", "nok", "phone"],
                "data": [["QZ#26-0101", "Ilvan Qorvat", "D/o Darro Qorvat", "+91 91111 22223"],
                         ["QZ#26-0102", "Morra Tesk", "W/o Yalen Tesk", "+91 92222 33334"]],
                "rowCount": 2}
        pf = _json(data)
        self.assertEqual(harvest.record_locs(pf), ["/data/0", "/data/1"])
        recs = harvest.harvest_file(pf)
        self.assertIn("Morra Tesk", recs[1].facts.names)
        self.assertTrue(any(t.startswith("phone:") for t in recs[0].facts.ids))
        assign = link(recs)[0]
        self.assertNotEqual(assign[("x/a.json", "/data/0")], assign[("x/a.json", "/data/1")])

    def test_columnar_cells_are_scrubbed(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from raksha import pipeline
        data = {"columns": ["uhid", "full_name", "phone"],
                "data": [["QZ/26/000111", "Ilvan Qorvat", "9111122223"], ["QZ/26/000112", "Morra Tesk", "9222233334"]]}
        with tempfile.TemporaryDirectory() as d:
            inp, out = Path(d) / "in", Path(d) / "out"
            inp.mkdir()
            (inp / "desk.json").write_text(json.dumps(data), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                pipeline.run(inp, out, b"unit-secret", {})
            body = (out / "sanitized" / "desk.json").read_text(encoding="utf-8")
        for v in ("Ilvan", "Morra", "9111122223", "000112"):
            self.assertNotIn(v, body)
        self.assertEqual(len(json.loads(body)["data"][1]), 3)

    def test_list_of_label_strings_without_rows_is_not_columnar(self):
        self.assertIsNone(harvest.columnar_rows({"columns": ["a", "b"], "notes": ["x", "y"]}))


class RoundFresh4MessageRows(unittest.TestCase):
    """Invented data: a message export whose body names a hospital number."""

    def test_message_row_with_hospital_number_links(self):
        sms = _csv(["msg_id", "sent_at", "to", "status", "body"],
                   [["SM-0001", "2026-01-02 09:00", "+91 91111 22223", "DELIVERED",
                     "Report ready for UHID QZH/26/004512. Collect from lab."],
                    ["SM-0002", "2026-01-02 09:05", "", "DELIVERED", "Camp on Sunday, all welcome."]],
                   rel="x/sms.csv")
        reg = _csv(["UHID", "Name", "Mobile"], [["QZH/26/004512", "Ilvan Qorvat", "9111122223"]], rel="x/reg.csv")
        recs = harvest.harvest_file(sms) + harvest.harvest_file(reg)
        self.assertTrue(recs[0].facts.is_patient)
        self.assertFalse(recs[1].facts.is_patient)
        m = link(recs)[0]
        self.assertIsNotNone(m[("x/sms.csv", "row:0")])
        self.assertEqual(m[("x/sms.csv", "row:0")], m[("x/reg.csv", "row:0")])
        self.assertIsNone(m[("x/sms.csv", "row:1")])


class DottedKeyAndKvRules(unittest.TestCase):
    """Dotted keys typed by their last segment, bank accounts, object numbers, key=value documents."""

    def test_dotted_person_prefix_types_by_last_segment(self):
        self.assertEqual(F.classify_label("insured.name"), F.NAME)
        self.assertEqual(F.classify_label("insured.house"), F.HOUSE)
        self.assertEqual(F.classify_label("insured.place"), F.VILLAGE)
        self.assertEqual(F.classify_label("insured.pin"), F.PIN)
        self.assertEqual(F.classify_label("insured.landline"), F.PHONE)
        self.assertEqual(F.classify_label("insured.uhid"), F.PATIENT_ID)
        self.assertEqual(F.classify_label("patient.addr.village"), F.VILLAGE)
        self.assertEqual(F.classify_label("proposer.name"), F.RELATIVE)
        self.assertEqual(F.classify_label("nominee.name"), F.RELATIVE)
        self.assertEqual(F.classify_label("insured.policy_no"), F.INSURANCE)
        self.assertEqual(F.classify_label("diagnosis.2"), F.CLINICAL)

    def test_dotted_facility_prefix_is_the_institution_number(self):
        self.assertEqual(F.classify_label("hospital.rohini_id"), F.OTHER_ID)
        self.assertEqual(F.classify_label("facility.phone"), F.OTHER_ID)

    def test_bank_account_labels(self):
        for lb in ("bank_ac", "Bank A/C", "A/C No", "Account No", "khata no", "proposer.bank_ac"):
            self.assertEqual(F.classify_label(lb), F.BANK, lb)
        self.assertEqual(F.classify_label("Account Holder Name"), F.NAME)
        self.assertTrue(F.is_pii_type(F.BANK))

    def test_object_number_labels_are_not_patient_ids(self):
        for lb in ("claim_batch", "settled_utr", "kit_lot", "sample_barcode"):
            self.assertEqual(F.classify_label(lb), F.OTHER_ID, lb)
        self.assertEqual(F.classify_column("claim_batch", ["9988776655", "9988776655"]), F.OTHER_ID)

    def test_alias_label_is_a_name(self):
        self.assertEqual(F.classify_label("alias"), F.NAME)
        self.assertEqual(F.classify_label("insured.aka"), F.NAME)

    def test_kv_document_slots(self):
        text = ("# pre-auth request\ninsured.name = Ravindra Pokharkar\ninsured.uhid = QX/26/004411\n"
                "insured.house = Kunnathu Veedu\nproposer.name = Suvarna\nward = Female Medical Ward\n"
                "diagnosis.1 = Lobar pneumonia\nproposer.bank_ac = 3041 7712 905\n")
        got = {lb: (text[a:b], t) for lb, a, b, t in harvest.kv_doc_slots(text)}
        self.assertEqual(got["insured.name"], ("Ravindra Pokharkar", F.NAME))
        self.assertEqual(got["insured.house"][1], F.HOUSE)
        self.assertEqual(got["proposer.name"][1], F.RELATIVE)
        self.assertEqual(got["proposer.bank_ac"][1], F.BANK)
        self.assertNotIn("ward", got)
        self.assertNotIn("diagnosis.1", got)
        self.assertEqual(harvest.kv_doc_slots("a = 1\nsome prose here\nmore prose\nand more\nb = 2\n"), [])

    def test_kv_document_id_links(self):
        text = ("insured.name = Ravindra Pokharkar\ninsured.uhid = QX/26/004411\ninsured.age = 61 Y\n"
                "ward = Female Medical Ward\ndiagnosis.1 = Lobar pneumonia\n")
        pf = ParsedFile(rel="x/preauth.txt", sha256="c" * 64, kind=KIND_TEXT, text=text)
        recs = harvest.harvest_file(pf)
        self.assertTrue(any("QX26004411" in i.replace("/", "") for i in recs[0].facts.ids), recs[0].facts.ids)
