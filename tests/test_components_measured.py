"""Independent scalar and fixture controls for the measured component gate."""
from itertools import product as assignments
from pathlib import Path
import random
import sys
import unittest

from ssr.components import measured as M
from ssr.components.view import parse

def records(lines):
    return [parse(line) for line in lines]


def mapping(rows, labels):
    return {str(i): label for i, label in zip([i for i, r in enumerate(rows) if r['code'] & 127 == M.K.HMR], labels)}


def scalar(rows, values, outcomes):
    q = {int(k[2:]): int(v) for k, v in values.items() if k.startswith('q:')}
    b = {int(k[2:]): int(v) for k, v in values.items() if k.startswith('b:')}
    phase = 0
    stack = []
    for i, r in enumerate(rows):
        t = r['code']
        c = t & 127
        qs, bit, bc = r['q'], r['b0'], r['bc']
        if t == M.K.PUSH_CONDITION:
            stack.append(bool(b.get(bc, 0)))
            continue
        if t == M.K.POP_CONDITION:
            stack.pop()
            continue
        if not all(stack) or (bc is not None and not b.get(bc, 0)):
            continue
        for w in qs:
            q.setdefault(w, 0)
        if c in (0x11, 0x21, 0x31):
            gate = 1
            for w in qs[:-1]:
                gate &= q[w]
            q[qs[-1]] ^= gate
        elif c == 0x22 or (c == 0x32 and q[qs[0]]):
            q[qs[-2]], q[qs[-1]] = q[qs[-1]], q[qs[-2]]
        elif c == 0x32:
            pass
        elif c in (0x00, 0x10, 0x20, 0x30, 0x13):
            predicate = 1
            for w in qs:
                predicate &= q[w]
            angle = int.from_bytes(bytes.fromhex(r['angle128_le_hex']), 'little') if c == 0x13 else 1 << 127
            phase = (phase+predicate*angle) % (1 << 128)
        elif c == 0x50:
            outcome = values['m:'+outcomes[str(i)]]
            phase = (phase+outcome*q[qs[0]]*(1 << 127)) % (1 << 128)
            q[qs[0]] = 0
            b[bit] = outcome
        elif c == 0x12:
            if q[qs[0]]:
                raise ValueError('dirty reset outside scalar proof grammar')
        elif c in (0x40, 0x41):
            b[bit] = int(c == 0x41)
        elif c == 0x42:
            b[bit] = b.get(bit, 0)^1
        elif c != 6:
            raise ValueError(c)
    assert not stack
    return q, b, phase


def evaluate(poly, values, labels):
    return sum(all(values.get(label, 0) for i, label in enumerate(labels) if int(m, 16) >> i & 1) for m in poly) % 2


def phase_evaluate(poly, values, labels):
    total = 0
    for m, coefficient in poly.items():
        if all(values.get(label, 0) for i, label in enumerate(labels) if int(m, 16) >> i & 1):
            total += int(coefficient, 16)
    return total % (1 << 128)


def fixtures():
    prefix = ['CCX q0 q1 q3', 'CX q2 q3']
    tail = ['BIT_INVERT b1 if b0', 'BIT_INVERT b2 if b1', 'Z q2 if b2']
    old = prefix+['HMR q3 b0']+tail
    new = prefix+['HMR q4 b0', 'Z q3 if b0']+tail
    same = old+['CCX q0 q1 q3'], new+['CX q2 q3']
    distinct = old+['CCX q0 q1 q5'], new+[
        'CX q3 q5', 'CX q2 q5', 'HMR q3 b3', 'CZ q0 q1 if b3', 'Z q2 if b3']
    return same, distinct


def guarded_fixture():
    return (['PUSH_CONDITION if b1', 'HMR q0 b0', 'BIT_STORE0 b1', 'X q2', 'POP_CONDITION'],
            ['HMR q0 b0 if b1', 'X q2 if b1', 'BIT_STORE0 b1 if b1'])


class TestMeasured(unittest.TestCase):
    def compare(self, old, new, *, zeros=(), private=()):
        a, b = records(old), records(new)
        labels_a = [f'root{i}' for i, r in enumerate(a) if r['code'] & 127 == M.K.HMR]
        labels_b = labels_a+[f'fresh{i}' for i, r in enumerate(b) if r['code'] & 127 == M.K.HMR][len(labels_a):]
        outcomes = dict(source=mapping(a, labels_a), child=mapping(b, labels_b))
        return M.compare(a, b, zero_qubits=zeros, private_records=private, outcomes=outcomes)

    def check_witness(self, old, new, result):
        self.assertFalse(result['equivalent'])
        values = {label: int(label in result['counterexample']['ones']) for label in result['variables']}
        a = scalar(records(old), values, result['outcome_mapping']['source'])
        b = scalar(records(new), values, result['outcome_mapping']['child'])
        a = (a[0], {k: v for k, v in a[1].items() if k not in result['private_records']}, a[2])
        b = (b[0], {k: v for k, v in b[1].items() if k not in result['private_records']}, b[2])
        kind = result['counterexample']['kind']
        if kind == 'phase':
            self.assertNotEqual(a[2], b[2])
        else:
            j = 0 if kind == 'quantum' else 1
            w = result['counterexample']['wire']
            self.assertNotEqual(a[j].get(w, values.get(('q:' if j == 0 else 'b:')+str(w), 0)),
                                b[j].get(w, values.get(('q:' if j == 0 else 'b:')+str(w), 0)))

    def test_retention_positive_and_independent_outcomes(self):
        for i, (old, new) in enumerate(fixtures()):
            result = self.compare(old, new, zeros=(3, 4), private=(3,) if i else ())
            self.assertTrue(result['equivalent'])
            self.assertEqual(result['signature_sha256'][0], result['signature_sha256'][1])
            for bits in assignments((0, 1), repeat=len(result['variables'])):
                values = dict(zip(result['variables'], bits))
                a = scalar(records(old), values, result['outcome_mapping']['source'])
                b = scalar(records(new), values, result['outcome_mapping']['child'])
                for w in set(a[0]) | set(b[0]):
                    self.assertEqual(a[0].get(w, values.get(f'q:{w}', 0)), b[0].get(w, values.get(f'q:{w}', 0)))
                for bit in {0, 1, 2}:
                    self.assertEqual(a[1].get(bit, values.get(f'b:{bit}', 0)), b[1].get(bit, values.get(f'b:{bit}', 0)))
                self.assertEqual(a[2], b[2])

    def test_fault_counterexamples(self):
        old, new = fixtures()[0]
        faults = [
            [line for line in new if line != 'Z q3 if b0'],
            [line for line in new if line != 'CX q2 q3'],
            [line for line in new if line != 'BIT_INVERT b1 if b0'],
            new[:4]+['BIT_STORE0 b0']+new[4:],
            new[:5]+['BIT_STORE0 b1']+new[5:],
        ]
        for child in faults:
            self.check_witness(old, child, self.compare(old, child, zeros=(3, 4)))
        self.check_witness(old, new, self.compare(old, new, zeros=(3,)))
        old, new = fixtures()[1]
        child = new+['BIT_INVERT b2 if b3']
        self.check_witness(old, child, self.compare(old, child, zeros=(3, 4), private=(3,)))

    def test_snapshot_guard_overwrite(self):
        old = ['PUSH_CONDITION if b0', 'BIT_STORE0 b0', 'X q0', 'POP_CONDITION']
        new = ['X q0 if b0', 'BIT_STORE0 b0 if b0']
        result = self.compare(old, new)
        self.assertTrue(result['equivalent'])
        self.check_witness(old, ['BIT_STORE0 b0 if b0', 'X q0 if b0'], self.compare(old, ['BIT_STORE0 b0 if b0', 'X q0 if b0']))

    def test_repeated_record_version_and_tiny_angle(self):
        lines = ['HMR q0 b0', 'BIT_INVERT b1 if b0', 'HMR q1 b0',
                 'Z_POW q2 angle128:00000000000000000000000000000001 if b1']
        self.assertTrue(self.compare(lines, lines)['equivalent'])
        wrong = lines[:-1]+[lines[-1].replace('0001 if', '0002 if')]
        self.check_witness(lines, wrong, self.compare(lines, wrong))
        self.assertTrue(self.compare(['HMR q0 b0', 'R q0'], ['HMR q0 b0'])['equivalent'])

    def test_guarded_hmr_and_overwritten_guard_scalar(self):
        old, new = guarded_fixture()
        result = self.compare(old, new)
        self.assertTrue(result['equivalent'])
        self.assertEqual(len(result['variables']), 5)
        for bits in assignments((0, 1), repeat=5):
            values = dict(zip(result['variables'], bits))
            a = scalar(records(old), values, result['outcome_mapping']['source'])
            b = scalar(records(new), values, result['outcome_mapping']['child'])
            self.assertEqual(a, b)
            signature = result['signatures'][0]
            for w, poly in signature['quantum'].items():
                self.assertEqual(a[0][int(w)], evaluate(poly, values, result['variables']))
            for w, poly in signature['records'].items():
                self.assertEqual(a[1][int(w)], evaluate(poly, values, result['variables']))
            self.assertEqual(a[2], phase_evaluate(signature['phase'], values, result['variables']))

    def test_fail_closed_interfaces(self):
        for lines in [['R q0'], ['POP_CONDITION'], ['PUSH_CONDITION if b0'],
                      ['BIT_INVERT b3'], ['X q0 if b3']]:
            with self.assertRaises((M.NotEntered, M.F.Barrier)):
                self.compare(lines, lines, private=(3,) if 'b3' in str(lines) else ())
        rows = records(['HMR q0 b0', 'HMR q1 b0'])
        with self.assertRaises(M.NotEntered):
            M.compare(rows, rows, outcomes=dict(source={'0': 'm', '1': 'm'}, child={'0': 'm', '1': 'n'}))
        with self.assertRaises(M.NotEntered):
            M.compare([], [], outcomes=dict(source={}, child={}), inherited_conditions=[{'record': 0}])
        inherited = [dict(parse('X q0'), condition_depth=1)]
        with self.assertRaises(M.NotEntered):
            M.compare(inherited, inherited, outcomes=dict(source={}, child={}))
        for lines in [['X q0']*513, [f'X q{i}' for i in range(129)]]:
            with self.assertRaises(M.NotEntered):
                self.compare(lines, lines)

    def test_wrong_alignment_is_visible(self):
        rows = records(['HMR q0 b0'])
        result = M.compare(rows, rows, outcomes=dict(source={'0': 'left'}, child={'0': 'right'}))
        self.assertFalse(result['equivalent'])

    def test_nonvacuous_generated_signature_panel(self):
        rng = random.Random(170031)
        checked = 0
        for case in range(40):
            lines = [f'X q{i}' for i in range(4)]+['BIT_INVERT b0', 'BIT_INVERT b1']
            for _ in range(12):
                gate = rng.choice(['X', 'CX', 'CCX', 'Z', 'CZ', 'CSWAP', 'SWAP', 'BIT_INVERT', 'Z_POW'])
                n = {'X': 1, 'CX': 2, 'CCX': 3, 'Z': 1, 'CZ': 2, 'CSWAP': 3, 'SWAP': 2, 'BIT_INVERT': 0, 'Z_POW': 1}[gate]
                line = gate+' '+(' '.join(f'q{i}' for i in rng.sample(range(4), n)) if n else f'b{rng.randrange(2)}')
                if gate == 'Z_POW':
                    line += ' angle128:00000000000000000000000000000001'
                if rng.randrange(2):
                    line += f' if b{rng.randrange(2)}'
                lines.append(line)
            lines += ['HMR q3 b1', 'BIT_INVERT b0 if b1', 'HMR q3 b1']
            result = self.compare(lines, lines)
            self.assertTrue(result['equivalent'])
            checked += 1
            signature = result['signatures'][0]
            for bits in assignments((0, 1), repeat=len(result['variables'])):
                values = dict(zip(result['variables'], bits))
                q, b, phase = scalar(records(lines), values, result['outcome_mapping']['source'])
                for w, poly in signature['quantum'].items():
                    self.assertEqual(q[int(w)], evaluate(poly, values, result['variables']))
                for w, poly in signature['records'].items():
                    self.assertEqual(b[int(w)], evaluate(poly, values, result['variables']))
                self.assertEqual(phase, phase_evaluate(signature['phase'], values, result['variables']))
        self.assertEqual(checked, 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
