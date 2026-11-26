from __future__ import annotations

import datetime as dt
import random
import unittest

from raksha.link import link
from raksha.types import Facts, Record

D = dt.date


def R(rel, loc, **kw):
    return Record(rel=rel, loc=loc, facts=Facts(**kw))


class LinkTest(unittest.TestCase):
    def same(self, m, a, b):
        self.assertIsNotNone(m[a])
        self.assertEqual(m[a], m[b])

    def test_same_uhid_different_formats(self):
        m, book = link([
            R("a.csv", "row:1", names=["Tarun Velkar"], ids=["uhid:QZH-4410"]),
            R("b.txt", "doc", names=["Tarun Velkar"], ids=["uhid:qzh4410"]),
        ])
        self.same(m, ("a.csv", "row:1"), ("b.txt", "doc"))
        self.assertEqual(list(book), ["uhid:QZH4410"])
        p = book["uhid:QZH4410"]
        self.assertEqual(p.records, sorted(p.records))
        self.assertEqual(len(p.facts), 2)

    def test_shared_phone_incompatible_names(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Kavli Dhoran"], ids=["uhid:QQ1", "phone:9000011122"]),
            R("a.csv", "row:2", names=["Bhimesh Tarpal"], ids=["uhid:QQ2", "phone:9000011122"]),
        ])
        self.assertNotEqual(m[("a.csv", "row:1")], m[("a.csv", "row:2")])

    def test_phone_merges_compatible(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Kavli Dhoran"], ids=["phone:+91 90000 11122"]),
            R("b.csv", "row:7", names=["Kavli Dhoran"], ids=["phone:9000011122"]),
        ])
        self.same(m, ("a.csv", "row:1"), ("b.csv", "row:7"))
        self.assertEqual(m[("a.csv", "row:1")], "phone:9000011122")

    def test_transitive_shared_phone_does_not_merge_families(self):
        # Two families each linked internally by uhid; one family member shares a phone with
        # the other family. The phone is demoted, so the families stay apart.
        m, _ = link([
            R("x.csv", "row:1", names=["Ornil Pashte"], ids=["uhid:F1", "phone:9111122233"]),
            R("x.csv", "row:2", names=["Ornil Pashte"], ids=["uhid:F1"]),
            R("y.csv", "row:1", names=["Gomti Rashval"], ids=["uhid:G1", "phone:9111122233"]),
            R("y.csv", "row:2", names=["Gomti Rashval"], ids=["uhid:G1"]),
            R("z.csv", "row:1", names=["Ornil Pashte"], ids=["phone:9111122233"]),
        ])
        self.assertEqual(m[("x.csv", "row:1")], "uhid:F1")
        self.assertEqual(m[("y.csv", "row:1")], "uhid:G1")
        self.assertNotEqual(m[("z.csv", "row:1")], "uhid:G1")

    def test_same_name_dob_merges(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Sunaina Kherval"], dob=D(1981, 3, 4), ids=["uhid:K77"]),
            R("n.txt", "doc", names=["Sunaina Kherval"], dob=D(1981, 3, 4)),
        ])
        self.same(m, ("a.csv", "row:1"), ("n.txt", "doc"))

    def test_latin_devanagari_merge_via_dob(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Ramesh Kumar"], dob=D(1970, 1, 2), ids=["uhid:LD1"]),
            R("h.txt", "doc", names=["रमेश कुमार"], dob=D(1970, 1, 2)),
        ])
        self.same(m, ("a.csv", "row:1"), ("h.txt", "doc"))

    def test_homonyms_stay_apart(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Devesh Patkar"], dob=D(1960, 5, 5), village="Lohgaon",
              age=64, ids=["uhid:H1"]),
            R("a.csv", "row:2", names=["Devesh Patkar"], dob=D(1990, 9, 9), village="Sirpur",
              age=34, ids=["uhid:H2"]),
            R("b.csv", "row:1", names=["Devesh Patkar"], village="Lohgaon", age=34),
        ])
        self.assertNotEqual(m[("a.csv", "row:1")], m[("a.csv", "row:2")])
        self.assertIsNone(m[("b.csv", "row:1")])

    def test_village_age_rule_and_uniqueness(self):
        recs = [
            R("a.csv", "row:1", names=["Jivika Sondre"], village="Kharbala", age=40, ids=["uhid:V1"]),
            R("b.csv", "row:1", names=["Jivika Sondre"], village="kharbala", age=41),
        ]
        m, _ = link(recs)
        self.same(m, ("a.csv", "row:1"), ("b.csv", "row:1"))
        recs.append(R("a.csv", "row:2", names=["Jivika Sondre"], village="Kharbala", age=40,
                      ids=["uhid:V2"]))
        m, _ = link(recs)
        self.assertIsNone(m[("b.csv", "row:1")])

    def test_relative_rule(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Pallavi Gondekar"], relatives=[("W/o", "Sudhir Gondekar")],
              ids=["uhid:RL1"]),
            R("t.txt", "doc", names=["Pallavi Gondekar"], relatives=[("पति", "Sudhir Gondekar")]),
        ])
        self.same(m, ("a.csv", "row:1"), ("t.txt", "doc"))

    def test_fragment_unique_only(self):
        base = [
            R("a.csv", "row:1", names=["Meghna Sutar"], relatives=[("D/o", "Harish Sutar")],
              ids=["uhid:FR1"]),
            R("f.txt", "doc", names=["Meghna"], relatives=[("D/o", "Harish")]),
        ]
        m, _ = link(base)
        self.same(m, ("a.csv", "row:1"), ("f.txt", "doc"))
        base.append(R("a.csv", "row:2", names=["Meghna Pawde"], relatives=[("D/o", "Harish Pawde")],
                      ids=["uhid:FR2"]))
        m, _ = link(base)
        self.assertIsNone(m[("f.txt", "doc")])

    def test_cannot_link_gender(self):
        m, _ = link([
            R("a.csv", "row:1", names=["Anshu Velte"], dob=D(2000, 1, 1), gender="M", ids=["uhid:G7"]),
            R("b.csv", "row:1", names=["Anshu Velte"], dob=D(2000, 1, 1), gender="F", ids=["uhid:G8"]),
        ])
        self.assertNotEqual(m[("a.csv", "row:1")], m[("b.csv", "row:1")])

    def test_not_patient_and_name_only(self):
        m, book = link([
            R("v.csv", "row:1", names=["Ojas Naru"], ids=["uhid:NP1"], is_patient=False),
            R("v.csv", "row:2", names=["Lalit Brava"]),
            R("v.csv", "row:3", names=["Lalit Brava"], ids=["phone:9222233344"]),
            R("v.csv", "row:4", names=["Hema Zirpe"], ids=["pan:ABCDE1234F"]),
        ])
        self.assertIsNone(m[("v.csv", "row:1")])
        self.assertIsNone(m[("v.csv", "row:2")])
        self.assertIsNone(m[("v.csv", "row:3")])
        self.assertEqual(m[("v.csv", "row:4")], "pan:ABCDE1234F")
        self.assertNotIn("uhid:NP1", book)

    def test_name_key_for_soft_group(self):
        m, book = link([
            R("a.csv", "row:1", names=["Tanvi Raskar"], dob=D(1999, 2, 3)),
            R("b.csv", "row:1", names=["Tanvi Raskar"], dob=D(1999, 2, 3)),
        ])
        key = m[("a.csv", "row:1")]
        self.assertTrue(key.startswith("name:") and key.endswith("|1999-02-03"))

    def test_shuffle_deterministic(self):
        recs = []
        for i in range(60):
            recs.append(R("f%d.csv" % (i % 3), "row:%d" % i, names=["Pers" + "aeiou"[i % 5] + "bdgk"[i % 4] + " Kalvar"],
                          dob=D(1950 + i % 20, 1, 1), ids=(["uhid:S%d" % (i % 7)] if i % 4 == 0 else [])))
        m1, b1 = link(recs)
        rnd = random.Random(7)
        for _ in range(3):
            sh = list(recs)
            rnd.shuffle(sh)
            m2, b2 = link(sh)
            self.assertEqual(m1, m2)
            self.assertEqual(sorted(b1), sorted(b2))

    def test_scale(self):
        import time
        def word(n, base):
            out = ""
            for _ in range(3):
                out += "bdgkmprstv"[n % 10] + "aeiou"[(n // 10) % 5]
                n //= 50
            return base + out

        recs = []
        for i in range(50000):
            recs.append(R("big.csv", "row:%d" % i, names=[word(i % 3000, "n") + " " + word(i % 97, "s")],
                          dob=D(1940 + i % 60, 1 + i % 12, 1 + i % 28),
                          village=word(i % 400, "g"), age=i % 90,
                          ids=["uhid:B%d" % (i // 2), "phone:9%09d" % (i % 20000)]))
        t = time.time()
        m, book = link(recs)
        self.assertLess(time.time() - t, 20)
        self.assertEqual(len(m), 50000)


if __name__ == "__main__":
    unittest.main()
