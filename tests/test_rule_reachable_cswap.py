"""Meaningful guards for the source-independent CSWAP rule."""

import tempfile
import unittest
from pathlib import Path

from support import need_kickmix
need_kickmix()
from ssr.rules import reachable_cswap as rule


def circuit(path, body):
    header = [f"APPEND_TO_REGISTER q{i} r0" for i in range(22)] + ['REGISTER r0 "x"']
    rule.km.Circuit("\n".join(header + body) + "\n").to_file(path, format="kmb")


class ReachableCswapTests(unittest.TestCase):
    def test_accepts_zero_effect_and_reproduces_one_op_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source.kmb"
            circuit(source, ["R q22", "R q23", "CSWAP q0 q22 q23"])
            found = rule.census(source)
            self.assertEqual(found["shared_noop_count"], 1)
            self.assertEqual(found["sites"][0]["op"], 2)
            candidate = root / "candidate.kmb"
            rule.delete(source, found["sites"][0]["handle"], candidate, found=found)
            self.assertEqual(rule.census(candidate)["unconditional_cswap_count"], 0)
            self.assertEqual(rule.census(candidate)["shared_noop_count"], 0)

    def test_rejects_effectful_swap_and_stale_handle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            positive = root / "positive.kmb"
            negative = root / "negative.kmb"
            circuit(positive, ["R q22", "R q23", "CSWAP q0 q22 q23"])
            circuit(negative, ["R q22", "R q23", "CX q1 q23", "CSWAP q0 q22 q23"])
            self.assertEqual(rule.census(negative)["shared_noop_count"], 0)
            handle = rule.census(positive)["sites"][0]["handle"]
            with self.assertRaises(ValueError):
                rule.delete(negative, handle, root / "bad.kmb")

    def test_excludes_rare_conditioned_gate_even_when_sampled_noop(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "conditional.kmb"
            circuit(source, ["R q22", "R q23", "CSWAP q0 q22 q23 if b999"])
            found = rule.census(source)
            self.assertEqual(found["unconditional_cswap_count"], 0)
            self.assertEqual(found["shared_noop_count"], 0)


if __name__ == "__main__":
    unittest.main()
