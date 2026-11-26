from __future__ import annotations

import base64
import unittest

from raksha import gate
from raksha.types import Facts, Patient


def fb_of(**kw):
    return gate.forbidden_from_book({"k1": Patient(key="k1", records=[("a.csv", "row:0")], facts=[Facts(**kw)])})


PHONE = "9876543210"


class GateTest(unittest.TestCase):
    def setUp(self):
        self.fb = fb_of(names=["Tavish Narkande"], ids=["phone:" + PHONE, "uhid:QXR-55120", "email:tavi.n@example.org"],
                        raw_ids=["QXR/55120"], relatives=[("S/o", "Bholu Narkande")])

    def kinds(self, text):
        return [k for _, _, k in gate.scan(text, self.fb)]

    def test_forbidden_shape(self):
        self.assertIn(PHONE, self.fb.digit_cores)
        self.assertIn("55120", self.fb.digit_cores)
        self.assertIn("tavi.n@example.org", self.fb.exact)
        self.assertIn(("narkande", "tavis"), self.fb.full_names)
        self.assertNotIn("Tavish", repr(self.fb))

    def test_phone_separators(self):
        for t in ("call 98765-43210 now", "call 98765 43210", "+91 98765.43210", "98/765/43/210"):
            self.assertEqual(self.kinds(t), ["DIGITS"], t)

    def test_phone_devanagari_digits(self):
        t = "फोन ९८७६५४३२१० है"
        hits = gate.scan(t, self.fb)
        self.assertEqual(len(hits), 1)
        s, e, _ = hits[0]
        self.assertEqual(t[s:e], "९८७६५४३२१०")

    def test_phone_inside_base64(self):
        enc = base64.b64encode(("contact " + PHONE + " please").encode()).decode()
        t = "note blob=" + enc + " end"
        hits = gate.scan(t, self.fb)
        self.assertEqual([k for _, _, k in hits], ["ENCODED"])
        s, e, _ = hits[0]
        self.assertEqual(t[s:e], enc)
        out, n = gate.clean(t, self.fb)
        self.assertGreater(n, 0)
        self.assertEqual(gate.scan(out, self.fb), [])
        self.assertTrue(out.startswith("note blob=[REDACTED]"))

    def test_percent_encoded(self):
        t = "x=98765%2D43210&y=1"
        self.assertEqual(self.kinds(t), ["ENCODED"])
        out, _ = gate.clean(t, self.fb)
        self.assertEqual(gate.scan(out, self.fb), [])

    def test_id_core_not_in_long_number(self):
        self.assertEqual(self.kinds("ts 20265512099"), [])
        self.assertEqual(self.kinds("UHID QXR 55120 seen"), ["DIGITS"])

    def test_exact_case_insensitive(self):
        self.assertEqual(self.kinds("mail TAVI.N@Example.org"), ["EXACT"])

    def test_names_any_order_and_script(self):
        self.assertEqual(self.kinds("Patient: Tavish Narkande"), ["NAME"])
        self.assertEqual(self.kinds("Narkande, Tavish"), ["NAME"])
        self.assertEqual(self.kinds("Tavish Kumar Narkande"), ["NAME"])
        self.assertEqual(self.kinds("मरीज़ तवीश नरकंडे"), ["NAME"])
        self.assertEqual(self.kinds("Tavish alone"), [])
        self.assertEqual(self.kinds("Tavish\nNarkande"), [])

    def test_relative_name(self):
        self.assertEqual(self.kinds("S/o Bholu Narkande"), ["NAME"])

    def test_doctor_allowed(self):
        self.assertEqual(self.kinds("Seen by Dr. Tavish Narkande today"), [])
        self.assertEqual(self.kinds("Seen by Dr Tavish Narkande"), [])
        self.assertEqual(self.kinds("डॉ. Tavish Narkande"), [])

    def test_clean_rescan_empty(self):
        t = "Tavish Narkande, ph 98765-43210, tavi.n@example.org, QXR/55120"
        out, n = gate.clean(t, self.fb)
        self.assertGreaterEqual(n, 4)
        self.assertEqual(gate.scan(out, self.fb), [])
        self.assertIn("[REDACTED]", out)

    def test_clean_keep_structure(self):
        t = 'id,a,b\n1,Tavish,Narkande\n'
        out, _ = gate.clean(t, self.fb, keep=',"\n')
        self.assertEqual(out, 'id,a,b\n1,[REDACTED],[REDACTED]\n')

    def test_empty_book(self):
        fb = gate.forbidden_from_book({})
        self.assertEqual(gate.scan("Tavish Narkande 9876543210", fb), [])


if __name__ == "__main__":
    unittest.main()
