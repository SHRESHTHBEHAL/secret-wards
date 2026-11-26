"""Free-text rule families (invented names and places only)."""
import unittest

from raksha import detect, patterns


def kinds(text, kind=None):
    return [(sp.kind, text[sp.start:sp.end]) for sp in detect.detect(text) if kind is None or sp.kind == kind]


def ids(text):
    return [(sp.kind, text[sp.start:sp.end]) for sp in patterns.find_identifiers(text)]


class PhoneShapes(unittest.TestCase):
    def test_landline_and_wrap(self):
        self.assertIn(("PHONE", "020 2553 0000"), ids("sister (Ph. 020 2553 0000)"))
        self.assertIn(("PHONE", "0389-2340000"), ids("call 0389-2340000 today"))
        self.assertIn(("PHONE", "90031\n77400"), ids("mob 90031\n77400"))

    def test_reference_veto(self):
        for t in ("Trip ID 8794000066", "package 9848000045", "Lab ref LRN-9845000067", "Ref no ABC/26/9830000045"):
            self.assertEqual([k for k, _ in ids(t) if k == "PHONE"], [], t)

    def test_partial_aadhaar(self):
        self.assertIn(("AADHAAR_MASKED", "4321"), ids("Aadhaar last four 4321 only"))
        self.assertEqual(ids("Hb last four days 9.1"), [])


class KeepValues(unittest.TestCase):
    def test_reference_numbers_not_patient_ids(self):
        for t in ("Lab No. Q-1234/26", "Cyto No Q-1187/26", "MLR No QX/26/77100"):
            self.assertEqual([sp for sp in patterns.find_patient_ids(t)], [], t)
        self.assertTrue(patterns.find_patient_ids("UHID No. QQ26-0091-5540"))

    def test_eponyms_and_schemes(self):
        t = "Forrest IIa ulcer; Orphan Annie nuclei; enrolled in Pradhan Sahayata Yojana and Mission Swasthya."
        self.assertEqual(kinds(t, "PERSON") + kinds(t, "PATIENT_NAME"), [])

    def test_institution_after_name(self):
        self.assertEqual(kinds("Referred to Ratanpur SDH for USG."), [])
        self.assertEqual(kinds("Accompanied by ASHA and nurse."), [])

    def test_history_of(self):
        self.assertEqual(kinds("H/O NSAID intake for two months.", "RELATIVE_NAME"), [])
        self.assertTrue(kinds("H/O Bikram Tandel, attendant.", "RELATIVE_NAME"))

    def test_police_station_kept(self):
        t = "निवासी ग्राम सोनपुरा, थाना रतनगढ़, जिला कोटा"
        self.assertFalse(any("रतनगढ़" in v for _, v in kinds(t)))


class NameFrames(unittest.TestCase):
    def test_name_before_age_sex(self):
        self.assertIn(("PATIENT_NAME", "Bhavik Tamrakar"), kinds("Seen Bhavik Tamrakar, 34/M today."))
        self.assertIn(("PATIENT_NAME", "Ojasvi Rane"), kinds("Patient Ojasvi Rane (F/57) reviewed"))
        self.assertEqual(kinds("Dr. Ojasvi Rane, 45/F", "PATIENT_NAME"), [])

    def test_lowercase_hinglish(self):
        t = "aaj tulsiya ke ghar gayi. pati bhimraj ne gaadi bulayi"
        got = [v for _, v in kinds(t)]
        self.assertIn("tulsiya", got)
        self.assertIn("bhimraj", got)
        self.assertEqual(kinds("pati ne bataya ki bukhar hai"), [])

    def test_slash_header(self):
        t = "Ketaki Pandit/41F/QMC2600999/OT-2/Dr. Vimal Joshi"
        got = kinds(t)
        self.assertIn(("PATIENT_NAME", "Ketaki Pandit"), got)
        self.assertIn(("MRN", "QMC2600999"), got)
        self.assertFalse(any("Vimal" in v for _, v in got))

    def test_declarant_and_third_party(self):
        self.assertIn(("PERSON", "Tarakesh"), kinds("I, Tarakesh, son of the patient"))
        self.assertTrue(kinds("documents couriered by Jharna Mookerjee, ABHA pending"))
        got = [v for _, v in kinds("sons Pravin and Ujjwal were informed")]
        self.assertEqual(got, ["Pravin", "Ujjwal"])

    def test_devanagari_pid_label(self):
        t = "भर्ती संख्या - कखग/२६/०१२३४"
        self.assertTrue(kinds(t, "MRN"))


class Addresses(unittest.TestCase):
    def test_house_and_lane(self):
        got = kinds("Correspondence address: # 4471, Sector 19-C, near Ratanpur water tank.")
        self.assertIn(("HOUSE", "# 4471"), got)
        self.assertIn(("LOCALITY", "Sector 19-C"), got)
        self.assertTrue(any(k == "LANDMARK" for k, _ in got))
        self.assertEqual(kinds("Block 2 nerve conduction normal"), [])

    def test_landmark_postposition(self):
        self.assertTrue(any(k in ("LANDMARK", "VILLAGE", "LOCALITY") for k, _ in kinds("ghar purani chakki ke paas hai")))
        self.assertTrue(kinds("हनुमान मंदिर के सामने रहते हैं", "LANDMARK"))
        self.assertEqual(kinds("near normal limits; behind the eye"), [])


def names(text):
    return [text[sp.start:sp.end] for sp in detect.detect(text) if sp.kind in detect.NAME_KINDS]


class Propagation(unittest.TestCase):
    def test_pet_form_and_lowercase(self):
        t = "[1/2/26, 9:01 pm] Teru: Pu Zarvanlianga admitted\n[1/2/26, 9:05 pm] Teru: lianga chu a dam"
        self.assertIn("lianga", names(t))

    def test_common_word_name_from_strong_anchor(self):
        t = "Mother Pooja says baby fed well. Pooja to return Monday."
        self.assertEqual(names(t).count("Pooja"), 2)

    def test_email_local_part(self):
        t = "From: Annabella Qorvo <anna.qorvo@mailbox.example>\nPlease see report.\nAnna"
        self.assertIn("Anna", names(t))

    def test_negative_no_anchor(self):
        self.assertEqual(names("Patient stable. Shanti and calm ward tonight."), [])
        t = "From: Records Desk <records@hospital.example>\nrecords attached"
        self.assertNotIn("records", names(t))


class Layout(unittest.TestCase):
    def test_wrapped_label_value(self):
        t = "Name of the Patient: Qorvani\nTelmara        Age 33\nUHID No.: QQH 26 0077\n1429\n"
        n = names(t)
        self.assertIn("Qorvani", n)
        self.assertIn("Telmara", n)
        self.assertIn(("MRN", "QQH 26 0077\n1429"), kinds(t, "MRN"))

    def test_wrap_negative(self):
        self.assertNotIn("Fever", names("Name: Qorvani\nFever since 3 days\n"))

    def test_letter_spaced_and_ocr_colon(self):
        t = "Pt  Name  :  Q O R V A        Age : 55\n"
        self.assertIn("Q O R V A", names(t))

    def test_pipe_table_header(self):
        t = ("Bed | Name | Age/Sex | Dx | Attendant / Ph\n"
             " 3  | Qorvan P. | 49/M | CKD 3 | wife Telmi 9437000018\n"
             " 6  | vacant |  |  |\n")
        n = names(t)
        self.assertIn("Qorvan P.", n)
        self.assertIn("Telmi", n)
        self.assertNotIn("vacant", n)

    def test_space_table_keep_column(self):
        t = ("Test            Day1      Ref range        Sample ID\n"
             "CSF protein     186       15-45            9864000045\n")
        self.assertEqual(kinds(t, "PHONE"), [])

    def test_space_key_value(self):
        t = "Victim            Q. Telmarong        M / ~27\nVitals            BP 124/80\n"
        n = names(t)
        self.assertIn("Q. Telmarong", n)
        self.assertNotIn("Vitals", n)


class ChatMailIntro(unittest.TestCase):
    def test_tilde_sender(self):
        t = "[21/02/26, 9:12 pm] +91 87298 00051: ~ Qormuii: operation done"
        self.assertIn("Qormuii", names(t))

    def test_intro_and_vocative(self):
        self.assertIn("Qordes", names("Caller: He is my father. I am Qordes, his daughter."))
        self.assertIn("Telmaben", names("Doctor: Telmaben, weight kitna hua?"))
        self.assertEqual(names("I am Fine, the patient said."), [])

    def test_drug_after_speaker_label(self):
        self.assertEqual(names("Caller: Foracort 200 two puffs twice a day."), [])


def surfaces(text):
    return [text[sp.start:sp.end] for sp in detect.detect(text)]


class PlacePhrases(unittest.TestCase):
    def test_type_word_before_and_after(self):
        self.assertIn("Qelpa Tola", surfaces("ASHA visited the house in Qelpa Tola with the AWW."))
        self.assertIn("Zorbak Nagar", surfaces("main Qira bol rahi hoon, Zorbak Nagar se, flat 3."))
        self.assertIn("qorvan patti", surfaces("komal, gaon qorvan patti, ko bukhar hai."))
        self.assertTrue(any("zelvi" in g for g in surfaces("06:00 so rahi hai. zelvi gaon se aayi thi.")))
        self.assertIn("Uttar Qorlapur Pt-III", surfaces("Ram of Uttar Qorlapur Pt-III came with cough."))

    def test_devanagari(self):
        self.assertIn("क्षोरम डीह", surfaces("जो ग्राम क्षोरम डीह के पास रहते हैं"))
        self.assertIn("ज़ोरगाव खुर्द", surfaces("श्री राम, रा. ज़ोरगाव खुर्द, ता. जुन्नर, यांना"))
        self.assertTrue(any("क्वेलति गांव" in g for g in surfaces("निवासी मकान सं. 2, डाकघर क्वेलति गांव, थाना सदर")))

    def test_frames_and_runs(self):
        self.assertIn("Qorvadi", surfaces("Hum log Qorvadi shift ho rahe hain."))
        self.assertIn("Zelpur Qosalli", surfaces("Attendant in waiting area: wife, from Zelpur Qosalli."))
        self.assertIn("Qurtovim", surfaces("We live in H. No. 7/3 Vazdem, Qurtovim, so the hospital is far."))
        self.assertIn("Qassavo", surfaces("House No. 21, Zairo Alto, Qassavo, Bardez 403000"))

    def test_keeps(self):
        t = "Post Op day 2. Sent via Email. Referred from PHC Qelpur. Patient from Ranchi, Jharkhand."
        got = surfaces(t)
        for w in ("Op", "Email", "Qelpur", "Ranchi", "Jharkhand"):
            self.assertFalse(any(w in g for g in got), (w, got))
        self.assertEqual([k for k, _ in kinds("जिला बांकुड़ा, थाना सदर") if k != "DISTRICT"], [])
        self.assertFalse(any("Light" in g for g in surfaces("Fever since 3 days, came from OPD.")))


class ProseNames(unittest.TestCase):
    def test_devanagari_unlabelled(self):
        self.assertIn("क्षेमधर मोहेर", surfaces("आज सुबह ६ बजे क्षेमधर मोहेर, उम्र लगभग ४७ वर्ष, को"))
        self.assertIn("ज़ामकृष्ण महतो", surfaces("महोदय, ज़ामकृष्ण महतो नामक ५८ वर्षीय पुरुष को"))
        self.assertIn("आशा किरण वैद्य", surfaces("रोगी: आशा किरण वैद्य        उम्र: ४४ वर्ष"))
        self.assertEqual([k for k in surfaces("आज सुबह ६ बजे मरीज़ को बुखार था।") if "बजे" in k], [])

    def test_latin_shapes(self):
        self.assertIn("Qilukuri V. N. S. Zrasad", surfaces("Mr Qilukuri V. N. S. Zrasad, 58/M, IP No 26"))
        self.assertIn("Qukhchain", surfaces("Alleged assault with lathi by a neighbour, one Qukhchain, at 19:00."))
        self.assertIn("qyoti zorgohain", surfaces("14:00 qyoti zorgohain ot se shift hui. lap chole done."))
        self.assertIn("qani", surfaces("21:00 bed 9 qani ko tremors zyada"))
        self.assertIn("Qarmistha", surfaces("15 mg ekhon. Qarmistha r phone off, amake koro"))
        self.assertIn("Qissy", surfaces("Counselled Qissy on home exercises."))

    def test_roles_and_negatives(self):
        self.assertEqual(surfaces("anm didi ko phone kiya, unhone bola"), [])
        self.assertEqual(surfaces("16:00 drain 30 ml serous. 18:00 pain score 6/10"), [])
        self.assertEqual(surfaces("Seen today in OPD. Reviewed Labs."), [])

    def test_own_key_affix(self):
        k = detect.Known(own_keys=frozenset({detect._word_key("Qalremzuati")}))
        t = "ward 3 bed 14. Remzuati is sleeping now"
        self.assertIn("Remzuati", [t[sp.start:sp.end] for sp in detect.detect(t, k)])


if __name__ == "__main__":
    unittest.main()


class FreshGeneralisation(unittest.TestCase):
    """Rule families from the fresh-suite round (invented names and places only)."""

    def _names(self, t):
        return [v for k, v in kinds(t) if k in ("PERSON", "PATIENT_NAME", "RELATIVE_NAME")]

    def test_eponym_shield(self):
        for t in ("Qorvex Fall Scale 40.", "Zandor Plimm score 6.", "Modified Ashworth grade 1+.", "Barthel Index 60/100.",
                  "Berg Balance 41.", "hemiarthroplasty (Austin Moore prosthesis)", "Hoehn and Yahr stage 3"):
            self.assertEqual(self._names(t), [], t)
        # a weak tail after an unknown run stays a person
        self.assertTrue(self._names("Pt Qamesh Vortu type 2 DM since 2019."))

    def test_brand_suffix(self):
        for t in ("taking Zylopa Plus 125 mg", "Son: Qarnokind-AT subah ek.", "Tab. Vortexa daily"):
            self.assertEqual(self._names(t), [], t)

    def test_reference_labels_not_mrn(self):
        for t in ("Preauth ID: PA-918273-2611", "Ref: REJ/QQ/26/001122", "Call ref TN/1111/2222",
                  "consultation id QSJ-HP-2611-11111", "Ambulance 108 vehicle QQ10-1234 arranged"):
            self.assertEqual([k for k, _ in kinds(t) if k == "MRN"], [], t)
        self.assertIn(("MRN", "QQK/OP/2026/11111"), kinds("OP ticket QQK/OP/2026/11111"))
        self.assertIn(("MRN", "11 222 3333 4444 5"), kinds("Form F. MCTS 11 222 3333 4444 5"))

    def test_phone_shapes(self):
        self.assertIn(("PHONE", "+971 50 111 2222"), ids("WhatsApp +971 50 111 2222 (son)"))
        self.assertIn(("PHONE", "(01234) 262418"), ids("office (01234) 262418."))
        self.assertTrue([k for k, _ in ids("Number hai nau-aath-ek-chhe-shunya, 43725.") if k == "PHONE"])
        self.assertEqual(ids("do din se bukhar, ek do baar ulti"), [])

    def test_localities(self):
        t = "Lives with wife at #87, 3rd Cross, Qorvanagar. Shifted from 7, Zinnia Society to Plot 2."
        got = kinds(t)
        self.assertIn(("LOCALITY", "Qorvanagar"), got)
        self.assertIn(("LOCALITY", "3rd Cross"), got)
        self.assertIn(("LOCALITY", "Zinnia Society"), got)
        self.assertEqual(kinds("Body handed over for Qorvawadi."), [])
        self.assertEqual(kinds("Qorvanagar Diagnostic & Polyclinic, Nadia"), [])

    def test_institutions_and_roles(self):
        for t in ("102 gaadi se Sadar Aspatal Qorvaganj le gayi.", "Sawan ko sulana hai, sahiya didi ko bata diya.",
                  "क्यूराम चन्द्र भंज चिकित्सा महाविद्यालय, कटक"):
            self.assertEqual([v for v in self._names(t) if v != "Sawan"], [], t)

    def test_footer_caps_and_dev_roles(self):
        self.assertIn(("PERSON", "Qolan Zedeng-Kowlni"),
                      kinds("-- printed by Qolan Zedeng-Kowlni ext 214 / 98373 60142 --"))
        self.assertIn(("PATIENT_NAME", "QORVATHAMBI M"), kinds("Dear QORVATHAMBI M, your appt is on 07-Nov."))
        self.assertEqual(kinds("Dear SIR, please find attached."), [])
        self.assertIn(("PERSON", "क्यूकेश ज़ैगर"), kinds("रक्तदाता: साला क्यूकेश ज़ैगर, वोटर कार्ड"))

    def test_clinical_hinglish_hindi(self):
        for t in ("Patient: ghutnon mein dard dono taraf.", "Background: Left MCA infarct (Aug 2026)",
                  "2. मैं बच्चेदानी निकालने का ऑपरेशन करवाने की सहमति देती हूँ।"):
            self.assertEqual(self._names(t), [], t)
        self.assertTrue(any(sp.kind == "LAB" for sp in patterns.protected_spans("हीमोग्लोबिन: 4.6 ग्राम/डी.एल.")))
        self.assertEqual([sp for sp in patterns.find_pins("बैग नं.: 340001-B")], [])


def mrns(text):
    return [text[sp.start:sp.end] for sp in patterns.find_patient_ids(text)]


def kin_names(text):
    return [(sp.kind, text[sp.start:sp.end]) for sp in detect.detect(text) if sp.kind in detect.NAME_KINDS]


class ReferenceNumbers(unittest.TestCase):
    def test_reference_numbers_kept(self):
        for t in ("came in auto KA-05-MN-1234 at night", "Hearse van UP 32 AB 9876 arranged",
                  "Req. No. BB/26/1100 urgent", "donor card D/26/4400", "Mortuary reg. PM/0101/26.",
                  "(X-ray no. X/26/10101)", "Dr. Q Rao, MCh (Uro), Reg KMC/FMR/10101", "SMC Reg SMC/R/00101",
                  "(pre-auth CMCHIS/XYZ/2601/10101)", "Implant LOT 10101010 used"):
            self.assertEqual(mrns(t) + [x for k, x in ids(t) if k in ("INSURANCE_ID", "AADHAAR", "PHONE")], [], t)
        self.assertEqual(ids("Lab Ref 260101000101 collected"), [])
        self.assertEqual([k for k, _ in ids("Booking ID 9830000001.")], [])

    def test_patient_numbers_removed(self):
        self.assertEqual(mrns("riding motorcycle no. KA-05-MN-1234."), ["KA-05-MN-1234"])
        self.assertEqual(mrns("RCH ID: 100000000101  date"), ["100000000101"])
        self.assertEqual(mrns("Nikshay ID 1000000101"), ["1000000101"])
        self.assertEqual(mrns("UHID: SMC-0000101"), ["SMC-0000101"])
        self.assertIn(("PHONE", "9830000001"), ids("Mob 9830000001"))


class ClinicalShields(unittest.TestCase):
    def test_history_and_complaint(self):
        for t in ("C/O: RTA - bike skid, pain Rt thigh", "B: smoker, h/o PTB 2010 (completed ATT).",
                  "I'm 30, h/o PCOS.", "k/c/o HTN; h/o tobacco (gutka); no DM", "Comorbid: Paroxysmal AF on drugs",
                  "Alleged RTA - skid from motorcycle at 02:00 hrs."):
            self.assertEqual(kin_names(t), [], t)
        self.assertEqual([k for k, _ in kin_names("Smt. Leela Devi H/O Ramprasad Yadav")], ["PATIENT_NAME", "RELATIVE_NAME"])

    def test_institutions_programmes_roles(self):
        for t in ("Referred from Kavya Nursing Home, Town Road.", "Sir Ratan Lal Memorial Hospital, Capital",
                  "Hello Noor Pharmacy, refill please", "Tab Albendazole on National Deworming Day",
                  "JSY Rs 1400 paid", "Tech: Dialysis Technician Gr-I on duty", "Lt Brescia-Cimino AVF working",
                  "Graham Steell murmur absent", "Police: Town Police Station informed"):
            self.assertEqual(kin_names(t), [], t)
        prot = patterns.protected_spans("HR 52/min, prostate 68 cc, found on NH-21 roadside")
        self.assertEqual(len(prot), 3)

    def test_people_and_places_still_found(self):
        self.assertIn(("PERSON", "Ramlal Khan Pathan"), kin_names("welder; employer Seth Ramlal Khan Pathan, Town"))
        self.assertTrue(any(k == "RELATIVE_NAME" for k, _ in kin_names("बेटा रामू यादव सूरत में काम करता है")))
        self.assertTrue(any(sp.kind in ("VILLAGE", "TEHSIL") for sp in detect.detect("R/o village X, tehsil Kotri, Jaipur.")))
        self.assertTrue(any(sp.kind == "DISTRICT" and "Imphal West" in "Add: Some Leikai, Imphal West"[sp.start:sp.end]
                            for sp in detect.detect("Add: Some Leikai, Imphal West")))


class InstitutionsWardsDiseases(unittest.TestCase):
    """Invented facility, ward and place names only."""

    def _gone(self, t):
        return [k for k, _ in kinds(t) if k in ("PERSON", "PATIENT_NAME", "RELATIVE_NAME", "VILLAGE", "LOCALITY")]

    def test_regional_institution_heads(self):
        for t in ("Vindhya Janseva Rugnalaya - Dawa ki Parchi", "VINDHYA JANSEVA RUGNALAYA, PUNE",
                  "Referred to Kesari Zila Chikitsalaya OPD", "Seen at Tapti Arogya Kendra today",
                  "Tamarai Maruthuvamanai discharge summary", "Saraswati Seva Sadan, ward 2"):
            self.assertEqual(self._gone(t), [], t)

    def test_named_wards(self):
        for t in ("वार्ड: Mahila Kaksh 3, बिस्तर 17", "Moved to Gahan Chikitsa Ikai", "Admitted to Asthi Rog Ward",
                  "Shifted to Nephro Step-down", "14:00 - Isolation Bay - stable.", "TIPPANI / Purush Kaksh 2 / Palang 12"):
            self.assertEqual(self._gone(t), [], t)

    def test_disease_names(self):
        for t in ("बीमारी: Kyasanur Forest disease (A98.2)", "1. Scrub typhus in any febrile patient",
                  "Japanese encephalitis vaccine given"):
            self.assertEqual(self._gone(t), [], t)
        self.assertTrue(self._gone("Ramesh Kumar fever x 3 days"))


class AddressAndIds(unittest.TestCase):
    def test_house_labels(self):
        self.assertIn(("HOUSE", "Door No. 3-117"), kinds("Domicile: Door No. 3-117, Kovil Street"))
        self.assertIn(("HOUSE", "Holding No. 302"), kinds("Home: C/O Ram Das, Holding No. 302, Ward No. 5, Nalbari Road"))

    def test_landmarks(self):
        self.assertIn(("LANDMARK", "KSRTC depot"), kinds("behind KSRTC depot"))
        self.assertIn(("LANDMARK", "Railway gumti"), kinds("near Railway gumti"))
        self.assertEqual(kinds("Patient came to the station near OPD", "LANDMARK"), [])

    def test_admission_numbers(self):
        self.assertIn(("MRN", "W26-00031"), kinds("TIPPANI / Palang 12 / Bharti W26-00031"))
        self.assertIn(("MRN", "W26-00031"), kinds("भर्ती W26-00031"))
        self.assertEqual(kinds("Bharti 25 saal ki hai", "MRN"), [])

    def test_international_phones(self):
        for t, v in (("Son abroad: +1 (415) 555-0134.", "+1 (415) 555-0134"), ("call 00971 50 123 4567", "00971 50 123 4567"),
                     ("+44 (20) 7946 0958", "+44 (20) 7946 0958")):
            self.assertIn(("PHONE", v), ids(t), t)
        self.assertEqual(ids("Hb 12.5 (11-15)"), [])


class NameFrames(unittest.TestCase):
    def test_given_name_cues(self):
        self.assertIn(("PATIENT_NAME", "Pallavi"), kinds("Walk-in, number not traced. Pallavi naam bataya."))
        self.assertIn(("PATIENT_NAME", "Pallavi"), kinds("Pallavi baideo ka report aa gaya"))
        self.assertIn(("PATIENT_NAME", "Mohan"), kinds("Mohan bhau ka BP 130/80"))

    def test_devanagari_name_before_kin(self):
        self.assertIn(("PATIENT_NAME", "कमली"), kinds("कमली, पत्नी रामू, को स्थिर हालत में घर भेजा।"))

    def test_village_frames(self):
        self.assertIn(("VILLAGE", "Kanholi"), kinds("Ramesh hai, Kanholi wala - file mix mat karna."))
        self.assertIn(("VILLAGE", "रामपुरा खेड़ा"), kinds("कमला, उम्र 60 वर्ष, रामपुरा खेड़ा से। बेटे के साथ आए।"))
        self.assertEqual(kinds("Sugar wala test", "VILLAGE"), [])

    def test_kinship_longest_match(self):
        self.assertIn(("RELATIVE_NAME", "कमला"), kinds("पुत्री कमला"))
        self.assertIn(("RELATIVE_NAME", "कमला"), kinds("पुत्रीकमला"))


class PersonalDocuments(unittest.TestCase):
    # every number, handle and name below is invented

    def covered(self, text, part, known=None):
        i = text.index(part)
        return any(sp.start <= i and sp.end >= i + len(part) for sp in detect.detect(text, known))

    def test_labelled_documents(self):
        for t, v in (("Passport No: K4419820", "K4419820"), ("पासपोर्ट: K4419820", "K4419820"),
                     ("Driving licence MH12 20110049871", "MH12 20110049871"),
                     ("seen with MH-12-2011-0049871", "MH-12-2011-0049871"),
                     ("A/c No: 50100234478812", "50100234478812"), ("khata sankhya 3344556677", "3344556677"),
                     ("खाता संख्या 3344556677", "3344556677"), ("राशन कार्ड संख्या 1022334455", "1022334455"),
                     ("Vehicle No: MH 12 AB 4471", "MH 12 AB 4471"), ("वाहन संख्या UP 32 KL 1188", "UP 32 KL 1188"),
                     ("RTA: hit by motorcycle MH 12 AB 4471", "MH 12 AB 4471"),
                     ("Jan Aadhaar: 1098765432", "1098765432"), ("Family ID 102938475610", "102938475610")):
            self.assertTrue(self.covered(t, v), t)

    def test_family_id_is_not_aadhaar(self):
        t = "Jan Aadhaar 2345 6789 0123"
        self.assertEqual([sp.kind for sp in detect.detect(t)], ["REF_ID"])

    def test_upi_and_obfuscated_email(self):
        for t, v in (("UPI: qorvik.tal@okaxis", "qorvik.tal@okaxis"), ("paid via 9812300045@ybl", "9812300045@ybl"),
                     ("mail qorvik.tal @ gmail.com", "qorvik.tal @ gmail.com"),
                     ("mail qorvik.tal(at)gmail(dot)com", "qorvik.tal(at)gmail(dot)com"),
                     ("mail qorvik.tal [at] gmail [dot] com", "qorvik.tal [at] gmail [dot] com")):
            self.assertTrue(self.covered(t, v), t)

    def test_broken_numbers(self):
        for t, v in (("Aadhaar 4 4 1 2 3 3 4 4 5 5 6 6", "4 4 1 2 3 3 4 4 5 5 6 6"), ("mob 98765 4\n3210", "98765 4\n3210"),
                     ("Aadhaar 2345  6789 01\n23", "2345  6789 01\n23"), ("call 81XXXXXX19", "81XXXXXX19")):
            self.assertTrue(self.covered(t, v), t)
        self.assertEqual([sp.kind for sp in detect.detect("Contact: 919656922594")], ["PHONE"])

    def test_compact_dob(self):
        for t in ("DOB 14031987", "Date of birth: 14031987", '"birth_date": "19870314"'):
            self.assertIn("DOB", [sp.kind for sp in detect.detect(t)], t)

    def test_keep_side(self):
        for t in ("Call 108 for ambulance; 104 helpline; toll free 1800-180-1104; 14555.",
                  "Platelets 150000-410000 /cumm", "TLC 4,000-11,000", "Platelets 150000", "Bed No 14", "Cot 22",
                  "Batch No B23104", "Lot 4471A", "Claim No CLM20240011", "Package code SG039A", "ICD-10 J18.9",
                  "SNOMED 233604007", "SpO2 98", "BP 130/85", "at 10:45 am", "for 3 weeks", "Bill Rs. 12,450",
                  "Amount ₹ 45000", "3 mo old", "18 months old", "UTR 234567890123 paid",
                  "drug licence no MH12 20110049871 of the chemist", "delivery bike KL 10 AX 7745 brought the strips",
                  "on account of fever since 3 days", "RTA: ambulance MH 12 AB 4471 brought him"):
            self.assertEqual([sp.kind for sp in detect.detect(t) if sp.kind != "AGE"], [], t)


class KnownNameForms(unittest.TestCase):
    def setUp(self):
        k = detect._word_key
        self.k = detect.Known(own_keys=frozenset({k("Qarunesh"), k("Bhadolia"), k("क़रुणेश")}),
                              full_names=((k("Qarunesh"), k("Bhadolia")),))

    def covered(self, text, part, known):
        i = text.index(part)
        return any(sp.start <= i and sp.end >= i + len(part) for sp in detect.detect(text, known))

    def test_forms(self):
        for t, v in (("Qarunesh ko bukhar tha", "Qarunesh"), ("qarunesh ne dawa li", "qarunesh"),
                     ("क़रुणेश को बुखार", "क़रुणेश"), ("QARUNESH came", "QARUNESH"),
                     ("seen Q A R U N E S H today", "Q A R U N E S H"), ("file qarunesh_bhadolia.pdf", "qarunesh"),
                     ("C:\\docs\\QaruneshBhadolia\\x.txt", "Qarunesh"), ("patient Qa ru nesh  Bhad-\nolia", "Qa ru nesh"),
                     ("patient Qa ru nesh  Bhad-\nolia", "Bhad-\nolia")):
            self.assertTrue(self.covered(t, v, self.k), t)

    def test_generic_given_name_before_postposition(self):
        k = detect.Known(own_keys=frozenset({detect._word_key("Ram"), detect._word_key("राम")}))
        self.assertTrue(self.covered("Ram ko bukhar", "Ram", k))
        self.assertTrue(self.covered("राम ने दवा ली", "राम", k))
        self.assertEqual(detect.detect("Dr. Ram ne dekha", k), [])
        self.assertEqual(detect.detect("Ram Manohar Lohia Hospital", k), [])


class WrappedNumberGuard(unittest.TestCase):
    """A complete phone at a line end must not swallow digits from the next line."""

    def test_time_on_next_line_survives(self):
        from raksha import patterns
        text = "18:40 - visitor at bed 12, mob 9876501234\n19:10 - evening round done."
        spans = patterns.find_identifiers(text)
        covered = "".join(text[s.start:s.end] if hasattr(s, "start") else text[s[0]:s[1]] for s in spans)
        self.assertIn("9876501234", covered)
        self.assertNotIn("\n", covered)
        self.assertNotIn("19", covered.replace("9876501234", ""))
