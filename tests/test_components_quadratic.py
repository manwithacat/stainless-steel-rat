from pathlib import Path
import itertools
import sys
import unittest
import numpy as np
from ssr.components import quadratic as Q
from ssr.components.view import parse

def scalar(records, values):
    s = dict(values)
    for r in records:
        c, q = r['code'], r['q']
        if c == 0x11:
            s[q[0]] ^= 1
        elif c == 0x21:
            s[q[1]] ^= s[q[0]]
        elif c == 0x31:
            s[q[2]] ^= s[q[0]] & s[q[1]]
        elif c == 0x22:
            s[q[0]], s[q[1]] = s[q[1]], s[q[0]]
        elif c == 0x32:
            if s[q[0]]:
                s[q[1]], s[q[2]] = s[q[2]], s[q[1]]
        elif c != 6:
            raise AssertionError(c)
    return s


class Controls(unittest.TestCase):
    def test_affine_products_exhaustively(self):
        rng = np.random.default_rng(912)
        tested = 0
        for _ in range(100):
            lines = []
            for _ in range(12):
                a, b = map(int, rng.choice(5, 2, replace=False))
                lines.append(f'CX q{a} q{b}')
            lines += ['X q0', 'CCX q0 q1 q5', 'CCX q2 q3 q6']
            for _ in range(10):
                a, b = map(int, rng.choice(7, 2, replace=False))
                lines.append(f'CX q{a} q{b}')
            records = [parse(s) for s in lines]
            sig, _ = Q.signature(records, list(range(7)))
            for bits in itertools.product((0, 1), repeat=7):
                values = dict(enumerate(bits))
                self.assertEqual(scalar(records, values), Q.evaluate(sig, values))
            tested += 1
        self.assertEqual(tested, 100)

    def test_overlap_constant_and_boolean_idempotence(self):
        for a in range(16):
            for b in range(16):
                p = Q.multiply(a, b, 3)
                for bits in itertools.product((0, 1), repeat=3):
                    x = sum(v << (i+1) for i, v in enumerate(bits)) | 1
                    def affine(v):return (v & x).bit_count() % 2
                    sig = dict(interface=[0, 1, 2], outputs={'0':hex(p)})
                    self.assertEqual(Q.evaluate(sig, dict(enumerate(bits)))[0], affine(a) & affine(b))
        self.assertEqual(Q.multiply(1001, 1001, 4), 1001)
        self.assertEqual(Q.multiply(1001, 1000, 4), 0)

    def test_wrong_map_and_unsupported_interfaces(self):
        r = [parse('CCX q0 q1 q2')]
        a, _ = Q.signature(r, [0, 1, 2])
        b, _ = Q.signature([], [0, 1, 2])
        self.assertNotEqual(a, b)
        for lines in [['CCX q0 q1 q2', 'CCX q2 q3 q4'], ['HMR q0 b0'],
                      ['Z q0'], ['Z_POW q0 angle128:00000000000000000000000000000001'],
                      ['CCX q0 q1 q2 if b0']]:
            with self.assertRaises(Q.Unsupported):Q.signature([parse(x) for x in lines], list(range(5)))

    def test_cswap_and_dense128_wire_case(self):
        records = [parse('CSWAP q0 q1 q2')]
        sig, _ = Q.signature(records, [0, 1, 2])
        for bits in itertools.product((0, 1), repeat=3):
            self.assertEqual(scalar(records, dict(enumerate(bits))), Q.evaluate(sig, dict(enumerate(bits))))
        lines = [f'CX q{i} q0' for i in range(2, 65)]+[f'CX q{i} q1' for i in range(65, 127)]+['CCX q0 q1 q127']
        records = [parse(x) for x in lines]
        sig, info = Q.signature(records, list(range(128)))
        self.assertGreater(info['maximum_output_monomials'], 512)
        rng = np.random.default_rng(194)
        for _ in range(32):
            values = {i:int(b) for i, b in enumerate(rng.integers(0, 2, 128))}
            self.assertEqual(scalar(records, values), Q.evaluate(sig, values))


if __name__ == '__main__':unittest.main()
