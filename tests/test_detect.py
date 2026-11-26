from __future__ import annotations

import datetime as dt
import time
import unittest

from raksha.detect import Known, detect, text_facts
from raksha.translit import name_key


def found(text, known=None, order="dmy"):
    return [(s.kind, text[s.start:s.end], s.value) for s in detect(text, known, order)]


def surfaces(text, kinds=None, known=None):
    return [x for k, x, _ in found(text, known) if kinds is None or k in kinds]


NAMES = ("PATIENT_NAME", "RELATIVE_NAME", "PERSON")

EN_HEADER = (
    "SUKHDHAM MULTISPECIALITY HOSPITAL, KANPUR\n"
    "DISCHARGE SUMMARY\n\n"
    "Patient Name: Kiran Bala        Age/Sex: 36 Yrs/F\n"
    "UHID: SKH/25/012345        IPD No: IPD-2025-00777\n"
    "W/o Rajan Bala\n"
    "Address: H.No. 12, Ward 14, Mohalla Purana Qila, near Bada Talab, Vill. Sundarpur, Tehsil Kheri, "
    "Distt. Sitapur - 261001\n"
    "Mobile: +91 91234 56789\n"
    "Consultant: Dr. Alok Mehra (MD Medicine)\n"
    "Ward/Bed: Ward 8 (Medicine) / Bed 23\n"
    "Date of Admission: 05/06/2025\n"
    "DOB: 03/04/1989\n\n"
    "Presenting complaints: C/O fever for 3 days, generalised weakness.\n"
    "Course in hospital: BP 161/93 mmHg, Pulse 82/min. Haemoglobin 7.6 g/dL. Kiran didi ki condition ab stable hai.\n"
    " 1. Tab Amlodipine 5 mg 0-0-1 x 30 days\n"
    "Advice: Review in OPD after 2 weeks with Dr. Alok Mehra.\n"
    "Attendant: Rajan Bala, Mob. 9123456789\n"
)

HI_HEADER = (
    "सुखधाम अस्पताल\n"
    "मरीज़ का नाम: सीमा वर्मा    आयु: 54 वर्ष / महिला\n"
    "पिता का नाम: हरिओम वर्मा\n"
    "पंजीकरण सं.: SKH-0012345    आईपीडी सं.: ADM000412\n"
    "पता: मकान नं. 77, शिव मंदिर के पास, ग्राम रामपुर कलां, तहसील बिसवां, जिला सीतापुर - 261145\n"
    "मोबाइल: ९८७६५४३२१०\n"
    "मरीज़ को 8 दिन से बुखार था। BP 120/83, Pulse 99/min।\n"
)


class EnglishHeader(unittest.TestCase):
    def setUp(self):
        self.f = found(EN_HEADER)
        self.kinds = {(k, x) for k, x, _ in self.f}

    def test_names(self):
        self.assertIn(("PATIENT_NAME", "Kiran Bala"), self.kinds)
        self.assertIn(("RELATIVE_NAME", "Rajan Bala"), self.kinds)
        self.assertIn(("PATIENT_NAME", "Kiran"), self.kinds)            # "Kiran didi ki"

    def test_ids_and_phone(self):
        self.assertIn(("MRN", "SKH/25/012345"), self.kinds)
        self.assertIn(("MRN", "IPD-2025-00777"), self.kinds)
        self.assertIn(("PHONE", "+91 91234 56789"), self.kinds)
        self.assertIn(("PHONE", "9123456789"), self.kinds)

    def test_address(self):
        for kind, x in (("HOUSE", "H.No. 12"), ("LOCALITY", "Ward 14"), ("LOCALITY", "Mohalla Purana Qila"),
                        ("LANDMARK", "near Bada Talab"), ("VILLAGE", "Sundarpur"), ("TEHSIL", "Kheri"),
                        ("DISTRICT", "Sitapur"), ("PIN", "261001")):
            self.assertIn((kind, x), self.kinds)

    def test_dob_age_gender(self):
        vals = {(k, v) for k, _, v in self.f}
        self.assertIn(("DOB", "1989-04-03"), vals)
        self.assertIn(("AGE", "36"), vals)
        self.assertIn(("GENDER", "F"), vals)

    def test_clinical_untouched(self):
        covered = "".join(x for _, x, _ in self.f)
        for keep in ("Alok", "Mehra", "Amlodipine", "161/93", "0-0-1", "7.6", "Ward 8", "fever", "05/06/2025"):
            self.assertNotIn(keep, covered)


class HindiHeader(unittest.TestCase):
    def test_block(self):
        k = {(a, b) for a, b, _ in found(HI_HEADER)}
        self.assertIn(("PATIENT_NAME", "सीमा वर्मा"), k)
        self.assertIn(("RELATIVE_NAME", "हरिओम वर्मा"), k)
        self.assertIn(("MRN", "SKH-0012345"), k)
        self.assertIn(("MRN", "ADM000412"), k)
        self.assertIn(("HOUSE", "मकान नं. 77"), k)
        self.assertIn(("LANDMARK", "शिव मंदिर के पास"), k)
        self.assertIn(("VILLAGE", "रामपुर कलां"), k)
        self.assertIn(("TEHSIL", "बिसवां"), k)
        self.assertIn(("DISTRICT", "सीतापुर"), k)
        self.assertIn(("PIN", "261145"), k)
        self.assertIn(("PHONE", "९८७६५४३२१०"), k)
        self.assertNotIn("मरीज़", "".join(b for _, b, _ in found(HI_HEADER)))

    def test_name_before_ko(self):
        t = "नाम: राधा मिश्रा   आयु: 44 वर्ष\nराधा मिश्रा को 3 दिन से खांसी है।"
        self.assertEqual(surfaces(t, NAMES), ["राधा मिश्रा", "राधा मिश्रा"])
        self.assertEqual(surfaces("गोपाल सक्सेना को 5 दिन से बुखार है।", NAMES), ["गोपाल सक्सेना"])
        self.assertEqual(surfaces("मरीज़ को 8 दिन से बुखार था।", NAMES), [])

    def test_unseen_labels(self):
        t = "Patient's Name: Rohit Verma   Contact No.: 98765 43210   Regn. #: RKH/25/012345\nRogi Naam: Pooja Saxena"
        k = {(a, b) for a, b, _ in found(t)}
        self.assertIn(("PATIENT_NAME", "Rohit Verma"), k)
        self.assertIn(("PATIENT_NAME", "Pooja Saxena"), k)
        self.assertIn(("PHONE", "98765 43210"), k)
        self.assertIn(("MRN", "RKH/25/012345"), k)


class Hinglish(unittest.TestCase):
    def test_honorifics(self):
        t = "Pradeep sahab ka BP 130/80. Meenakshi didi ki report aayi. Tarun bhai ki condition stable. Report of Lata ji"
        self.assertEqual(surfaces(t, NAMES), ["Pradeep", "Meenakshi", "Tarun", "Lata"])
        self.assertIn("BP 130/80", t)
        self.assertNotIn("130", "".join(surfaces(t)))

    def test_whatsapp_header(self):
        t = "[12/03/25, 8:15 pm] Vinod Bhaiya: <attachment: report.pdf>\nReport of Meena ji  52 Y / F\ncall karo 98123 45670"
        f = found(t)
        self.assertIn(("RELATIVE_NAME", "Vinod", "Bhaiya"), f)
        self.assertIn(("PATIENT_NAME", "Meena", ""), f)
        self.assertIn(("PHONE", "98123 45670", "9812345670"), f)


class Kinship(unittest.TestCase):
    def test_fragment(self):
        f = found("Neelam, W/o Kishore, discharged in stable condition.")
        self.assertEqual([(k, x) for k, x, _ in f], [("PATIENT_NAME", "Neelam"), ("RELATIVE_NAME", "Kishore")])

    def test_all_caps_guardian(self):
        self.assertIn(("RELATIVE_NAME", "BHARAT CHOUDHARY", "S/o"), found("Guardian: S/O BHARAT CHOUDHARY"))

    def test_care_of_name_vs_complaint(self):
        t = ("Address (attendant): C/O Mahesh Gupta, Ward 5\nOPD: C/O fever for 4 days\nWard: 6 (Surgery)\n"
             "Medicine: Ramipril 5 mg\nDr. Mahesh Gupta reviewed the patient.")
        f = found(t)
        self.assertIn(("RELATIVE_NAME", "Mahesh Gupta", "C/O"), f)
        self.assertIn(("LOCALITY", "Ward 5", ""), f)
        self.assertEqual(len([x for x in f if x[0] in NAMES]), 1)       # the doctor stays
        covered = "".join(x for _, x, _ in f)
        for keep in ("fever", "Ward: 6", "Ramipril"):
            self.assertNotIn(keep, covered)

    def test_attendant_in_brackets(self):
        self.assertIn(("RELATIVE_NAME", "Kamini", "W/o"), found("Attendant (W/o Kamini) informed about diet."))


class Protected(unittest.TestCase):
    def test_eponyms_doses_vitals(self):
        t = ("Patient seen with Parkinson's disease and Bell's palsy, referred to Dr. Anil Kapoor. "
             "Tab Levodopa 100 mg BD x 5 days. BP 117/82, SpO2 96%. Range 70-140. ASHA worker informed.")
        self.assertEqual(found(t), [])

    def test_ward_as_ward(self):
        self.assertEqual(found("Ward 8 (Medicine), Bed 2 - routine round."), [])


class Canary(unittest.TestCase):
    def test_name_near_phone(self):
        t = "18:40 - Tenzing Rabgyal (attendant, bed 12), mob 6910522119"
        f = found(t)
        self.assertIn(("PERSON", "Tenzing Rabgyal", ""), f)
        self.assertIn(("PHONE", "6910522119", "6910522119"), f)

    def test_person_verbs(self):
        self.assertIn("Ilamaran Chakraborty", surfaces("Complaint raised by Ilamaran Chakraborty, callback 6069100011."))
        self.assertIn("Pemba Lhamo", surfaces("Consent witnessed by Pemba Lhamo, phone 8010000510."))
        self.assertIn("Harshit Thakur", surfaces("OPD note for Harshit Thakur. Mobile 8723300011. C/O cough."))


class KnownNames(unittest.TestCase):
    def test_across_scripts(self):
        k = Known(own_keys=frozenset({name_key("Meena"), name_key("Rastogi")}),
                  full_names=((name_key("Vinod"), name_key("Saran")),),
                  id_values=frozenset({"ABC25099887"}))
        t = "मीना रस्तोगी ने दवा ली. MEENA came with Saran Vinod. Old id ABC/25/099887."
        f = found(t, k)
        self.assertIn(("PATIENT_NAME", "मीना रस्तोगी", ""), f)
        self.assertIn(("PATIENT_NAME", "MEENA", ""), f)
        self.assertIn(("PERSON", "Saran Vinod", ""), f)
        self.assertIn(("MRN", "ABC/25/099887", "ABC25099887"), f)

    def test_generic_alone_skipped(self):
        k = Known(own_keys=frozenset({name_key("Devi"), name_key("Kumar")}))
        self.assertEqual(found("devi kumar ok", k), [])


class Facts(unittest.TestCase):
    def test_text_facts(self):
        f = text_facts(EN_HEADER)
        self.assertEqual(f.names[0], "Kiran Bala")
        self.assertIn(("W/o", "Rajan Bala"), f.relatives)
        self.assertIn("uhid:SKH25012345", f.ids)
        self.assertIn("enc:IPD202500777", f.ids)
        self.assertIn("phone:9123456789", f.ids)
        self.assertEqual(f.dob, dt.date(1989, 4, 3))
        self.assertEqual((f.age, f.gender), (36, "F"))
        self.assertEqual((f.village, f.tehsil, f.district, f.pin), ("Sundarpur", "Kheri", "Sitapur", "261001"))
        self.assertIn("H.No. 12", f.address_parts)
        self.assertEqual(f.ref_date, dt.date(2025, 6, 5))

    def test_empty_and_speed(self):
        self.assertEqual(detect(""), [])
        big = EN_HEADER * 2
        t0 = time.time()
        for _ in range(5):
            detect(big)
        self.assertLess((time.time() - t0) / 5, 0.25)

    def test_deterministic_sorted(self):
        a = detect(EN_HEADER + HI_HEADER)
        self.assertEqual(a, detect(EN_HEADER + HI_HEADER))
        for x, y in zip(a, a[1:]):
            self.assertLessEqual(x.end, y.start)


if __name__ == "__main__":
    unittest.main()


class DefectFixTests(unittest.TestCase):
    """Invented names / ids only."""

    def test_possessive_known_name(self):
        k = Known(own_keys=frozenset({name_key("Tanvika")}))
        t = "Sample received from Tanvika's attendant (W/o Rohan Velu)"
        self.assertIn(("PATIENT_NAME", "Tanvika"), [(a, b) for a, b, _ in found(t, k)])

    def test_possessive_anchored_name(self):
        self.assertIn("Morvi", surfaces("Report of Morvi's mother", NAMES))

    def test_possessive_eponym_protected(self):
        k = Known(own_keys=frozenset({name_key("Bell"), name_key("Parkinson")}))
        self.assertEqual(surfaces("Known Parkinson's disease, bell's palsy.", NAMES, k), [])

    def test_apostrophe_inside_name_kept(self):
        self.assertIn("D'Souza Ferrao", surfaces("Seen with D'Souza Ferrao today", NAMES))

    def test_asha_worker_never_person(self):
        for t in ("Referred by ASHA worker of the village.", "Referred by the ASHA of the village.",
                  "Brought by ASHA didi today.", "Informed ASHA workers yesterday."):
            self.assertEqual(surfaces(t, NAMES), [], t)

    def test_asha_first_name_still_patient(self):
        self.assertIn(("PATIENT_NAME", "Asha"), [(a, b) for a, b, _ in found("Asha, W/o Kamal Deore, 30 F")])
        self.assertIn(("PATIENT_NAME", "Asha"), [(a, b) for a, b, _ in found("Report of Asha ji")])

    def test_ward_after_relative_is_locality(self):
        f = found("C/O Bhanudas Yeole, Ward 8")
        self.assertIn(("RELATIVE_NAME", "Bhanudas Yeole"), [(a, b) for a, b, _ in f])
        self.assertIn(("LOCALITY", "Ward 8"), [(a, b) for a, b, _ in f])
        self.assertEqual(found("Ward 8 (Medicine) / Bed 23"), [])
        self.assertEqual(found("Ward: 4 (Medicine)"), [])

    def test_respectful_word_is_patient(self):
        f = text_facts("Zubeida amma ka BP 112/74, bukhar utar gaya hai.")
        self.assertEqual(f.names, ["Zubeida"])
        self.assertEqual(f.relatives, [])

    def test_chat_sender_still_relative(self):
        f = text_facts("[12/03/2026] Kamlesh Bhaiya: kal aayenge")
        self.assertEqual(f.names, [])
        self.assertEqual([n for _, n in f.relatives], ["Kamlesh"])

    def test_lowercase_name_before_honorific(self):
        self.assertEqual(surfaces("tarla ji ka bp theek hai", NAMES), ["tarla"])
        self.assertEqual(surfaces("devraj sahab aaye", NAMES), ["devraj"])
        self.assertEqual(surfaces("nimmi didi ki report aayi", NAMES), ["nimmi"])
        for t in ("aap ji", "unki didi aayi", "mata ji ka bp", "doctor sahab ne dekha", "sister didi"):
            self.assertEqual(surfaces(t, NAMES), [], t)

    def test_devanagari_title_honorific_names(self):
        self.assertEqual(surfaces("कल श्रीमती सुरभि खरवार आईं", NAMES), ["सुरभि खरवार"])
        self.assertEqual(surfaces("उनको गिरिधर जी लाए", NAMES), ["गिरिधर"])
        self.assertEqual(surfaces("आज विमला देवी आईं", NAMES), ["विमला देवी"])
        self.assertEqual(surfaces("फिर श्री तेजपाल आए", NAMES), ["तेजपाल"])

    def test_header_line_name(self):
        self.assertEqual(surfaces("Sunbeam Lab Report of Charvi Tamhane 52 Y / F", NAMES), ["Charvi Tamhane"])
        self.assertEqual(surfaces("Metro Hospital OPD note for Hemant Jadhavrao.", NAMES), ["Hemant Jadhavrao"])

    def test_underscore_joined_surname_and_number(self):
        k = Known(own_keys=frozenset({name_key("Ravina")}))
        t = "D:\\HIS\\exports\\Ravina_Tondon_051234\\visits_2026_01.json"
        got = [(a, b) for a, b, _ in found(t, k)]
        self.assertIn(("PATIENT_NAME", "Ravina"), got)
        self.assertIn(("PATIENT_NAME", "Tondon"), got)
        self.assertIn(("MRN", "051234"), got)
