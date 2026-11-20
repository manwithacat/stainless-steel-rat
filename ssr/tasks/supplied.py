# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Exact current-function parity construction on an explicit input support.

The agent supplies a source-bound context; the rule never infers clean words
or turns a sampled state into a theorem. Adapted from the independently
audited RT195–197/219 constructor.
"""
import hashlib
import json

class Refused(ValueError):
    pass

class Unsupported(ValueError):

    def __init__(self, reason, at, row, **details):
        self.report = dict(status='UNSUPPORTED_PREFIX', reason=reason, at=at, row=row, **details)
        super().__init__(reason)

def xor(values):
    result = 0
    for value in values:
        result ^= value
    return result

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def solve(columns, target):
    rows = {}
    for i, value in enumerate(columns):
        code = 1 << i
        while value:
            pivot = value.bit_length() - 1
            if pivot not in rows:
                rows[pivot] = (value, code)
                break
            row, c = rows[pivot]
            value ^= row
            code ^= c
    residual, code = (target, 0)
    for pivot in sorted(rows, reverse=True):
        if residual >> pivot & 1:
            row, c = rows[pivot]
            residual ^= row
            code ^= c
    if not residual:
        assert xor((v for i, v in enumerate(columns) if code >> i & 1)) == target
        return dict(status='SPAN', coefficient=code, rank=len(rows))
    dual = residual & -residual
    for pivot in sorted(rows):
        if (dual & rows[pivot][0]).bit_count() & 1:
            dual ^= 1 << pivot
    assert (dual & target).bit_count() & 1
    assert not any(((dual & c).bit_count() & 1 for c in columns))
    return dict(status='NONMEMBER', dual=dual, rank=len(rows))

def address_truth(rows, mask):
    return sum((int(a & mask == mask) << a for a in range(rows)))

class Model:

    def __init__(self, values, rows, dirty_variables, contract):
        self.values = list(values)
        self.rows = rows
        self.dirty_variables = dirty_variables
        self.full = (1 << rows) - 1
        self.contract = contract
        self.depth = 0
        self.initial = self.values.copy()
        if any((v < 0 or v >> rows + dirty_variables for v in values)):
            raise Refused('VALUE_COORDINATE_OUTSIDE_CONTRACT')

    def columns(self, target):
        return [dict(kind='X', value=self.full)] + [dict(kind='CX', wire=q, value=v) for q, v in enumerate(self.values) if q != target and v]

    def validate(self, row, result):
        if row != result['original'] or row['name'] != 'CCX' or row['condition'] is not None or self.depth:
            raise Refused('SOURCE_ROW_OR_SCOPE_MISMATCH')
        a, b, target = row['q']
        if self.values[a] >> self.rows or self.values[b] >> self.rows:
            raise Refused('DIRTY_CONTROL')
        wanted = self.values[a] & self.values[b]
        available = self.columns(target)
        selected = result['selected_columns']
        if any((column not in available for column in selected)):
            raise Refused('UNAVAILABLE_CURRENT_COLUMN')
        refs = [c.get('wire', 'constant') for c in selected]
        if len(refs) != len(set(refs)) or target in refs:
            raise Refused('ALIASED_OR_SELF_CONTROL')
        if xor((c['value'] for c in selected)) != wanted or result['product_value'] != wanted:
            raise Refused('WRONG_PRODUCT_IDENTITY')
        replacement = [dict(name=c['kind'], q=[target] if c['kind'] == 'X' else [c['wire'], target], b=None, condition=None) for c in selected]
        if replacement != result['replacement'] or result['value_state_sha256'] != digest(self.values):
            raise Refused('EXECUTABLE_EXPRESSION_OR_STATE_MISMATCH')
        return True

    def try_ccx(self, row, at):
        a, b, target = row['q']
        if len(set(row['q'])) != 3:
            raise Refused('ALIASED_CCX')
        dirty = [self.values[q] >> self.rows for q in (a, b)]
        if any(dirty):
            raise Unsupported('DIRTY_CONTROL_PRODUCT', at, row, dirty_control_masks=dirty)
        wanted = self.values[a] & self.values[b]
        columns = self.columns(target)
        proof = solve([v['value'] for v in columns], wanted)
        if proof['status'] == 'NONMEMBER':
            return dict(at=at, status='NO_CURRENT_PARITY', rank=proof['rank'], dual=proof['dual'], product_value=wanted)
        selected = [c for i, c in enumerate(columns) if proof['coefficient'] >> i & 1]
        result = dict(at=at, status='SUPPLIED_FUNCTION_EDIT', original=row, product_value=wanted, selected_columns=selected, value_state_sha256=digest(self.values), replacement=[dict(name=c['kind'], q=[target] if c['kind'] == 'X' else [c['wire'], target], b=None, condition=None) for c in selected], Toffoli_delta=-1, quantum_header_delta=0, classical_header_delta=0)
        self.validate(row, result)
        return result

    def step(self, row, at, search=True):
        name, q = (row['name'], row['q'])
        if name == 'PUSH_CONDITION':
            self.depth += 1
            return None
        if name == 'POP_CONDITION':
            self.depth -= 1
            if self.depth < 0:
                raise Refused('NEGATIVE_CONDITION_DEPTH')
            return None
        if name == 'Z_POW':
            raise Unsupported('ROTATION_FORBIDDEN_IN_ANGLE_TASK', at, row)
        if name in ('NEG', 'Z', 'CZ', 'CCZ', 'INFO_TAG', 'BIT_STORE0', 'BIT_STORE1', 'BIT_INVERT'):
            return None
        if row['condition'] is not None or self.depth:
            raise Unsupported('GUARDED_QUANTUM_DATA_WRITE', at, row, depth=self.depth)
        if name in ('R', 'HMR') and len(q) == 1:
            self.values[q[0]] = 0
        elif name == 'X' and len(q) == 1 and (row['b'] is None):
            self.values[q[0]] ^= self.full
        elif name == 'CX' and len(q) == 2 and (row['b'] is None):
            self.values[q[1]] ^= self.values[q[0]]
        elif name == 'SWAP' and len(q) == 2 and (row['b'] is None):
            self.values[q[0]], self.values[q[1]] = (self.values[q[1]], self.values[q[0]])
        elif name == 'CCX' and len(q) == 3 and (row['b'] is None):
            trial = self.try_ccx(row, at)
            if search and trial['status'] == 'SUPPLIED_FUNCTION_EDIT':
                return trial
            self.values[q[2]] ^= self.values[q[0]] & self.values[q[1]]
            return trial if search else None
        else:
            raise Unsupported('UNSUPPORTED_QUANTUM_OR_CLASSICAL_DATA_FORM', at, row)
        return None

    def scan(self, program):
        trials = []
        for at, row in enumerate(program):
            try:
                trial = self.step(row, at)
            except Unsupported as error:
                return dict(**error.report, processed_operations=at, tested_CCX=len(trials), trials=trials, prefix_state_sha256=digest(self.values), contract=self.contract)
            if trial:
                trials.append(trial)
                if trial['status'] == 'SUPPLIED_FUNCTION_EDIT':
                    return dict(status='SUPPLIED_FUNCTION_EDIT', processed_operations=at + 1, tested_CCX=len(trials), trials=trials, candidate=trial, contract=self.contract)
        if self.depth:
            raise Refused('UNCLOSED_CONDITION_DEPTH')
        return dict(status='COMPLETE_NO_CURRENT_PARITY', processed_operations=len(program), tested_CCX=len(trials), trials=trials, final_values=self.values, contract=self.contract)
