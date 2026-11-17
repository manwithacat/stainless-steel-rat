"""Value-rank census: exclude free affine recovery, never nonlinear rebuilds."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ssr.core.evaluator import validate_contract, sha
from ssr.qhdl import bitsim as B, kmb as K
from ssr.workbench.structure import _layout


def _insert(basis, value, witness):
    while value:
        pivot = value.bit_length() - 1
        if pivot not in basis:
            basis[pivot] = (value, witness)
            return None
        v, w = basis[pivot]
        value ^= v
        witness ^= w
    return witness


def ranks(columns, wires, nrows, protected=()):
    """Columns are nonnegative packed ints. Witnesses are panel identities."""
    if len(columns) != len(wires) or nrows <= 0:
        raise ValueError('invalid column panel')
    mask = (1 << nrows) - 1
    linear, affine = {}, {}
    _insert(affine, mask, 1)
    relations = []
    for i, (q, value) in enumerate(zip(wires, columns)):
        value &= mask
        _insert(linear, value, 0)
        relation = _insert(affine, value, 1 << (i + 1))
        if relation is not None and q not in protected and len(relations) < 8:
            relations.append({'wire': int(q), 'xor_wires': [int(wires[j]) for j in range(i)
                              if relation & (1 << (j + 1))], 'constant': relation & 1,
                              'scope': 'identity on this panel only; validate before construction'})
    full = len(affine) - 1 == len(wires)
    return {'live_wires': list(map(int, wires)), 'linear_rank': len(linear),
            'affine_rank': len(affine) - 1, 'full_affine_rank': full,
            'panel_relations': relations}


def census(path, contract, work, *, points=64, panel_rows=4096, cuts=None):
    contract = validate_contract(contract)
    if type(points) is not int or not 1 <= points <= 4096:
        raise ValueError('points must be 1..4096')
    if type(panel_rows) is not int or not 1 <= panel_rows <= 4096:
        raise ValueError('panel_rows must be 1..4096')
    state = sha(path)
    k = K.read(path)
    if k.num_qubits > 260:
        raise ValueError('rank census width cap is 260')
    regs = k.registers
    if (len(regs) != 1 or regs[0][0] != 'x' or len(regs[0][1]) != contract['width']
            or not all(r[0] for r in regs[0][1])):
        raise ValueError('invsqrt x register mismatch')
    xq = [int(r[1]) for r in regs[0][1]]
    if len(set(xq)) != len(xq):
        raise ValueError('duplicate input wire')
    # Conversion metadata is authenticated by the same helper as admission.
    from ssr.core.evaluator import InvSqrtEvaluator
    exported = InvSqrtEvaluator(contract, work).export(path)
    ops, _header, parsed_x = B.parse_kmx(exported)
    if parsed_x != xq or len(ops) != len(k.op_types):
        raise ValueError('export does not preserve op indices/registers')
    iv, profile, registers, *_ = _layout(k)
    peak = int(profile.max()) if len(profile) else len(registers)
    eligible = np.flatnonzero(profile == peak).tolist()
    if cuts is None:
        selected = [eligible[i] for i in np.linspace(0, len(eligible)-1, min(points, len(eligible)), dtype=int)] if eligible else []
    else:
        if not isinstance(cuts, list) or not cuts or len(cuts) > 4096 or any(
                type(c) is not int or not 0 <= c < len(ops) for c in cuts):
            raise ValueError('cuts must be 1..4096 op indices in range')
        selected = sorted(set(cuts))
    rows = np.unique(np.linspace(1, contract['max_x'], min(panel_rows, contract['max_x']), dtype=np.int64))
    panel_hash = hashlib.sha256(rows.astype('<u8').tobytes()).hexdigest()
    live = {}
    protected = set(xq)
    for cut in selected:
        active = set(iv['logical'][(iv['s'] <= cut) & (iv['e'] >= cut)].tolist()) | protected
        live[cut] = xq + sorted(active - protected)
    results = {cut: {'cut_before_op': cut, 'models': []} for cut in selected}
    for outcome in ('zero', 7, 101):
        sim = B.BitSim(ops, rows=rows, num_qubits=k.num_qubits, x_qubits=xq, outcome=outcome)

        def snapshot(cut, sim):
            columns = [int.from_bytes(sim.q[q].astype('<u8').tobytes(), 'little') for q in live[cut]]
            results[cut]['models'].append({'outcome': outcome, **ranks(columns, live[cut], len(rows), protected)})

        sim.run(snaps=selected, on_snap=snapshot)
        del sim
    full = 0
    for result in results.values():
        excluded = any(m['full_affine_rank'] for m in result['models'])
        full += int(excluded)
        result['free_affine_recovery_excluded'] = excluded
        result['interpretation'] = ('park must pay a nonlinear rebuild or change the interface'
                                    if excluded else 'affine relation possible on panel; requires full-domain validation')
    if sha(path) != state:
        raise ValueError('circuit changed during census')
    return {'schema': 'ssr-rank-liveness/1', 'state_sha256': state,
            'declared_qubits': int(k.num_qubits), 'live_peak': peak,
            'eligible_peak_boundaries': len(eligible), 'sampled_boundaries': len(selected),
            'panel_rows': len(rows), 'panel_rows_sha256': panel_hash,
            'panel_selection': 'unique integer linspace(1,max_x); fixed outcome schedules zero/7/101',
            'cut_semantics': 'values before op; static occupancy intervals [first touch,last touch/reset] inclusive; inputs pinned',
            'full_rank_boundaries': full, 'full_rank_share': full / len(selected) if selected else None,
            'free_affine_candidate_windows_filtered': full,
            'filter_scope': 'free affine recovery only; paid nonlinear park/recompute remains eligible',
            'all_measurement_histories': False,
            'scope': 'full rank is a counterexample to any affine identity on this fixed interface; panel relations are not proofs',
            'cuts': list(results.values())}
