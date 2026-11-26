from __future__ import annotations

import unittest

from raksha.pseudo import CROCKFORD, Keys


class PseudoTest(unittest.TestCase):
    def test_empty_secret_rejected(self):
        with self.assertRaises(ValueError):
            Keys(b"")

    def test_format_and_stability(self):
        k = Keys(b"alpha-secret")
        p = k.pseudonym("uhid:TST0001")
        self.assertTrue(p.startswith("PSN-"))
        self.assertEqual(len(p), 14)
        self.assertTrue(all(c in CROCKFORD for c in p[4:]))
        self.assertEqual(p, Keys(b"alpha-secret").pseudonym("uhid:TST0001"))
        self.assertNotEqual(p, k.pseudonym("uhid:TST0002"))

    def test_differs_across_secrets(self):
        self.assertNotEqual(Keys(b"one").pseudonym("uhid:X1"), Keys(b"two").pseudonym("uhid:X1"))
        self.assertNotEqual(Keys(b"one").opaque("f.csv"), Keys(b"two").opaque("f.csv"))

    def test_forbidden_digits_rederive(self):
        k = Keys(b"forbid")
        base = k.pseudonym("uhid:Z9")
        digits = "".join(c for c in base if c.isdigit())
        if len(digits) >= 5:
            other = k.pseudonym("uhid:Z9", forbidden_digits=[digits[:5]])
            self.assertNotEqual(base, other)
            self.assertNotIn(digits[:5], "".join(c for c in other if c.isdigit()))
        # short strings are ignored
        self.assertEqual(base, k.pseudonym("uhid:Z9", forbidden_digits=["1234"]))

    def test_shift_days_range_nonzero_both_signs(self):
        k = Keys(b"shift")
        vals = [k.shift_days("uhid:P%d" % i) for i in range(400)]
        for v in vals:
            self.assertTrue(30 <= abs(v) <= 180)
        self.assertTrue(any(v < 0 for v in vals) and any(v > 0 for v in vals))
        self.assertEqual(k.shift_days("uhid:P1"), Keys(b"shift").shift_days("uhid:P1"))
        self.assertTrue(all(1 <= abs(k.shift_days("k%d" % i, 3, 1)) <= 3 for i in range(50)))

    def test_opaque(self):
        k = Keys(b"opq")
        o = k.opaque("file-a", 8)
        self.assertEqual(len(o), 8)
        self.assertTrue(all(c in CROCKFORD for c in o))
        self.assertEqual(o, k.opaque("file-a", 8))

    def test_no_secret_leak(self):
        k = Keys(b"very-private-secret")
        self.assertNotIn("very-private", repr(k))
        self.assertNotIn("very-private", str(k))
        self.assertFalse(hasattr(k, "__dict__"))
        for name in k.__slots__:
            self.assertNotEqual(getattr(k, name), b"very-private-secret")


if __name__ == "__main__":
    unittest.main()


class ShiftBookTest(unittest.TestCase):
    def test_distinct_offsets_while_they_last(self):
        from raksha.pseudo import Keys, ShiftBook
        keys = ["uhid:P%04d" % i for i in range(250)]
        sb = ShiftBook(Keys(b"s"), keys, 180, 30)
        offs = [sb.get(k) for k in keys]
        self.assertEqual(len(set(offs)), 250)
        self.assertTrue(all(30 <= abs(o) <= 180 for o in offs))

    def test_deterministic_and_order_free(self):
        from raksha.pseudo import Keys, ShiftBook
        keys = ["k%d" % i for i in range(80)]
        a = ShiftBook(Keys(b"s"), keys); b = ShiftBook(Keys(b"s"), list(reversed(keys)))
        self.assertEqual([a.get(k) for k in keys], [b.get(k) for k in keys])
        c = ShiftBook(Keys(b"other"), keys)
        self.assertNotEqual([a.get(k) for k in keys], [c.get(k) for k in keys])

    def test_overflow_spreads_evenly(self):
        from raksha.pseudo import Keys, ShiftBook
        keys = ["k%d" % i for i in range(700)]
        sb = ShiftBook(Keys(b"s"), keys, 180, 30)
        import collections
        load = collections.Counter(sb.get(k) for k in keys)
        self.assertLessEqual(max(load.values()), 3)
