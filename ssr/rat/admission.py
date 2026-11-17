"""Engine-priced, all-legal-input admission with explicit finite outcome coverage.

The task engine supplies the official shot schedule and equations, not the
official simulator. BitSim additionally counts *every* dirty reset. A guarded
transition must pass the existing activating-subspace screen. None of these
finite outcome panels is an exhaustive measurement-history proof.
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path

import numpy as np

from ssr.native.adapter import NativeProbe
from ssr.core.evaluator import InvSqrtEvaluator, VERIFIER, V, sha
from ssr.qhdl import alloutcome as AO, bitsim as B, kmb as K


class AdmissionProbe(NativeProbe):
    def __init__(self, engine_python, contract):
        super().__init__(engine_python, contract)
        self.task_module = importlib.import_module('kickmix_engine.invsqrt')
        cache = importlib.import_module('kickmix_engine.cache')
        for module in (self.task_module, cache, AO, B, K):
            self.identity[str(Path(module.__file__))] = sha(module.__file__)
        self.identity[str(Path(__file__))] = sha(__file__)

    def _load(self, path, work):
        # Export cache binds both source bytes and derived text. It does not
        # trust basename reuse, or execute code supplied alongside a circuit.
        exported = InvSqrtEvaluator(self.contract, work).export(path)
        ops, _header, xq = B.parse_kmx(exported)
        k = K.read(path)
        regs = k.registers
        if (len(regs) != 1 or regs[0][0] != 'x' or
                len(regs[0][1]) != self.contract['width'] or
                not all(r[0] for r in regs[0][1]) or
                [int(r[1]) for r in regs[0][1]] != xq or len(set(xq)) != len(xq)):
            raise ValueError('invalid x register')
        if k.num_qubits > 260:
            raise ValueError('admission width cap is 260')
        return ops, xq, k.num_qubits

    def _audit(self, rows):
        target, tol = V.reference_values(self.spec, rows.astype(np.uint64))

        def audit(sim):
            err = (sim.phase_units() - target).view(np.int64)
            used = np.abs(err).view(np.uint64)  # includes signed-min as 2**63
            bad = np.flatnonzero(used > tol)
            result = {'x_restored': bool(sim.x_restored()),
                      'scratch_clean': bool(sim.scratch_clean()),
                      'dirty_reset_count': int(sim.dirty),
                      'phase_bad_rows': int(len(bad)),
                      'first_bad_x': int(rows[bad[0]]) if len(bad) else None}
            result['valid'] = (result['x_restored'] and result['scratch_clean']
                               and not sim.dirty and not len(bad))
            return result
        return audit

    def evaluate(self, path, *, work, threads=3, group_chunks=16):
        self._guard()
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError('threads must be 1..4')
        start = time.monotonic()
        state = sha(path)
        ops, xq, nq = self._load(path, work)
        rows = np.arange(1, self.contract['max_x'] + 1, dtype=np.int64)
        audit = self._audit(rows)
        models = []
        for outcome in ('zero', 7, 101):
            sim = B.BitSim(ops, rows=rows, num_qubits=nq, x_qubits=xq, outcome=outcome)
            sim.run()
            models.append({'outcome': outcome, **audit(sim)})
            del sim
            if not models[-1]['valid']:
                break
        valid = len(models) == 3 and all(m['valid'] for m in models)
        pricing = None
        if valid:
            if self.spec.num_shots % 256:
                raise ValueError('engine pricing requires max_x * official_shots_per_x divisible by 256; no padding is substituted')
            try:
                pricing = self.task_module.InvSqrtTask(path, spec=self.spec, verifier_path=str(VERIFIER)).verify(
                    threads=threads, group_chunks=group_chunks)
            except AssertionError as exc:
                valid = False
                pricing = {'status': 'FAIL', 'error': str(exc)}
        self._guard()
        if sha(path) != state:
            raise ValueError('circuit changed during admission')
        return {'schema': 'ssr-admission/2', 'state_sha256': state,
                'declared_qubits': int(nq), 'contract': self.contract,
                'backend_sha256': self.identity, 'valid_on_native_models': valid,
                'loss_estimate': pricing['score'] if pricing and pricing['status'] == 'PASS' else None,
                'loss_scope': 'engine reproduction of default-salt official shot schedule and cost equations; no padding',
                'full_domain_rows_per_model': len(rows), 'models': models,
                'dirty_reset_check': 'cumulative at every executed R, under each listed schedule',
                'all_measurement_histories': False,
                'coverage': 'zero + independent 7/101 bit-sliced schedules; engine 64 shots/x for the default contract',
                'transition_requirement': 'parent-bound activating-subspace screen, including dirty reset counts',
                'pricing': pricing, 'tier': 'local admission prescreen',
                'seconds': time.monotonic() - start}

    def transition(self, parent, child, *, work, max_targets=60):
        self._guard()
        before = {'parent': sha(parent), 'child': sha(child)}
        ops1, xq, nq1 = self._load(parent, work)
        ops2, xq2, nq2 = self._load(child, work)
        if xq != xq2:
            raise ValueError('transition changes input wire mapping')
        rows = np.arange(1, self.contract['max_x'] + 1, dtype=np.int64)
        report = AO.check(ops1, ops2, xq, nq1=nq1, nq2=nq2, rows=rows,
                          max_targets=max_targets, rand_runs=2, audit=self._audit(rows))
        self._guard()
        if before != {'parent': sha(parent), 'child': sha(child)}:
            raise ValueError('transition input changed during admission')
        return {'schema': 'ssr-transition-admission/1', 'parent_sha256': before['parent'],
                'state_sha256': before['child'], 'all_measurement_histories': False,
                'valid_on_native_models': report['verdict'] == 'EQUIVALENT_ON_ACTIVATING_SAMPLES',
                'screen': report}
