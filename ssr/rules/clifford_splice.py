#!/usr/bin/env python3
"""Deterministic RAT opportunity: splice two sibling invsqrt KMBs at a common block, with free Clifford phase repair."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from ssr.qhdl import bitsim as B  # noqa: E402
from ssr.qhdl import exec as E  # noqa: E402

from ssr.rules import reachable_cswap as CS

QTR = np.uint64(1 << 62)
MAX_EXCEPTIONS = 64


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def anchor(donor_ops, host_ops, min_ops=1024):
    a = [o.text for o in donor_ops]
    b = [o.text for o in host_ops]
    blocks = [m for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
              if m.size >= min_ops]
    if not blocks:
        raise ValueError(f"no shared contiguous {min_ops}-op anchor")
    m = min(blocks, key=lambda x: (x.a, x.b))
    return m.a, m.b, m.size


def live_in_records(ops):
    written, needed = set(), set()
    for o in ops:
        if o.cond >= 0 and o.cond not in written:
            needed.add(o.cond)
        if o.code == B.C_BINV and o.bit not in written:
            needed.add(o.bit)
        if o.code in (B.C_HMR, B.C_BINV, B.C_BST0, B.C_BST1):
            written.add(o.bit)
    return sorted(needed)


def interface(donor, host, donor_cut, host_cut, branch, rows=None):
    do, dx, dn = donor
    ho, hx, hn = host
    d = B.BitSim(do, rows=rows, num_qubits=dn, x_qubits=dx, outcome=branch).run(stop=donor_cut)
    h = B.BitSim(ho, rows=rows, num_qubits=hn, x_qubits=hx, outcome=branch).run(stop=host_cut)
    if not np.array_equal(d.q, h.q):
        return None, None, "quantum cut state differs"
    needed = live_in_records(ho[host_cut:])
    if any(not np.array_equal(d._bit(i), h._bit(i)) for i in needed):
        return None, None, "future-live classical record differs"
    return d, h, None


def mask_for_rows(n, exceptions):
    out = np.zeros((n + 63) // 64, np.uint64)
    for i in exceptions:
        out[i // 64] |= np.uint64(1) << np.uint64(i % 64)
    return out


def support_signature(arrays, mask, exceptions):
    h = hashlib.blake2b(digest_size=20)
    sigs = []
    empty = True
    for a in arrays:
        outside = a & ~mask
        h.update(outside.tobytes())
        empty &= not np.any(outside)
        sigs.append(sum(((int(a[i // 64]) >> (i % 64)) & 1) << j
                        for j, i in enumerate(exceptions)))
    return h.hexdigest(), tuple(sigs), bool(empty)


def gate_key(g):
    return ({"Z_POW": 0, "CZ": 1, "NEG_IF": 2}[g["kind"]], g["ids"], g["angle"])


def render(g):
    if g["kind"] == "Z_POW":
        return f'Z_POW q{g["ids"][0]} {g["angle"] / 2:.1f}'
    if g["kind"] == "CZ":
        return f'CZ q{g["ids"][0]} q{g["ids"][1]}'
    return f'NEG if b{g["ids"][0]}'


def gate_support(g, sim):
    if g["kind"] == "Z_POW":
        return sim.q[g["ids"][0]]
    if g["kind"] == "CZ":
        x, y = g["ids"]
        return sim.q[x] & sim.q[y]
    return sim._bit(g["ids"][0])


def find_repair(states, written_bits, exceptions, target, *, targets_by_branch=None):
    """Find ≤2 exact free Clifford gates; optional targets vary by HMR branch."""
    sims = [d for d, _ in states]
    if targets_by_branch is None:
        targets_by_branch = [target] * len(states)
    if len(targets_by_branch) != len(states) or any(len(t) != len(exceptions) for t in targets_by_branch):
        raise ValueError("one target vector per branch and exception is required")
    mask = mask_for_rows(sims[0].n, exceptions)
    candidates = []

    def add(kind, ids, angles):
        descriptor = {"kind": kind, "ids": ids}
        arrays = [gate_support(descriptor, s) for s in sims]
        digest, sigs, empty = support_signature(arrays, mask, exceptions)
        for angle in angles:
            candidates.append({**descriptor, "angle": angle, "digest": digest,
                               "sigs": sigs, "off_empty": empty})

    for q in range(sims[0].nq):
        add("Z_POW", [q], (1, 2, 3))
    for q in range(sims[0].nq):
        for r in range(q + 1, sims[0].nq):
            add("CZ", [q, r], (2,))
    for bit in sorted(written_bits):
        if all(np.array_equal(d._bit(bit), h._bit(bit)) for d, h in states):
            add("NEG_IF", [bit], (2,))

    def matches(gates):
        for br in range(len(states)):
            for j, value in enumerate(targets_by_branch[br]):
                amount = sum(g["angle"] for g in gates if (g["sigs"][br] >> j) & 1) % 4
                if amount != value:
                    return False
        return True

    one = [g for g in candidates if g["off_empty"] and matches((g,))]
    grouped = defaultdict(list)
    for g in candidates:
        grouped[g["digest"]].append(g)
    two = []
    for group in grouped.values():
        for i, g in enumerate(group):
            for h in group[i:]:
                if not g["off_empty"] and (g["angle"] + h["angle"]) % 4:
                    continue
                if matches((g, h)):
                    two.append((g, h))
    one.sort(key=gate_key)
    two.sort(key=lambda pair: (gate_key(pair[0]), gate_key(pair[1])))
    chosen = [one[0]] if one else list(two[0]) if two else None
    if chosen:
        for br, (d, h) in enumerate(states):
            phase = np.zeros(d.n, np.uint8)
            for gate in chosen:
                support = B.unpack_bits(gate_support(gate, d), d.n).astype(np.uint8)
                phase += np.uint8(gate["angle"]) * support
            phase &= np.uint8(3)
            want = np.zeros(d.n, np.uint8)
            want[np.array(exceptions, dtype=np.int64)] = np.array(targets_by_branch[br], np.uint8)
            if not np.array_equal(phase, want):
                raise AssertionError(f"chosen gate full phase mismatch branch {br}")
    clean = lambda g: {k: g[k] for k in ("kind", "ids", "angle")}
    return ([clean(g) for g in chosen] if chosen else None,
            {"gate_entries": len(candidates), "outside_support_classes": len(grouped),
             "one_matches": len(one), "two_matches": len(two)})


def discover(donor_path, host_path, expected_donor=None, expected_host=None):
    dp, hp = Path(donor_path), Path(host_path)
    ds, hs = sha(dp), sha(hp)
    if expected_donor and ds != expected_donor or expected_host and hs != expected_host:
        raise ValueError("source SHA drift")
    do, dh, dx, dn = CS._ops(dp)
    ho, hh, hx, hn = CS._ops(hp)
    if (dh, dx, dn) != (hh, hx, hn) or dn > 64:
        raise ValueError("register interface mismatch or >64 wires")
    dc, hc, length = anchor(do, ho)
    donor, host = (do, dx, dn), (ho, hx, hn)
    states = []
    phase_target = None
    for branch in ("zero", 7, 101):
        d, h, error = interface(donor, host, dc, hc, branch)
        if error:
            raise ValueError(f"{branch}: {error}")
        delta = h.phase_units() - d.phase_units()
        if np.any(delta % QTR):
            raise ValueError(f"{branch}: correction not Clifford quarter turns")
        quarter = (delta // QTR).astype(np.uint8)
        nonzero = np.flatnonzero(quarter)
        if len(nonzero) > MAX_EXCEPTIONS:
            raise ValueError(f"{branch}: {len(nonzero)} phase exceptions exceed {MAX_EXCEPTIONS}")
        signature = (nonzero.tolist(), quarter[nonzero].tolist())
        if phase_target is None:
            phase_target = signature
        elif phase_target != signature:
            raise ValueError("phase correction differs across outcome models")
        states.append((d, h))
    exceptions, target = phase_target
    written_d = {o.bit for o in do[:dc] if o.code in (B.C_HMR, B.C_BINV, B.C_BST0, B.C_BST1)}
    written_h = {o.bit for o in ho[:hc] if o.code in (B.C_HMR, B.C_BINV, B.C_BST0, B.C_BST1)}
    gates, search = find_repair(states, written_d & written_h, exceptions, target)
    if gates is None:
        raise ValueError("no exact one/two free-Clifford repair")
    report = {"donor_sha256": ds, "host_sha256": hs, "donor_cut": dc, "host_cut": hc,
              "common_anchor_ops": length, "phase_exceptions": [i + 1 for i in exceptions],
              "quarter_turn_correction": target, "repair_gates": gates,
              "repair_op_text": [render(g) for g in gates], "search": search,
              "tier": "all legal invsqrt x in zero/seed7/seed101 HMR models; exact cut state and packed Clifford correction; candidate still needs official verifier"}
    return report, (dh, do, ho)


def emit(report, source_parts, out):
    header, donor_ops, host_ops = source_parts
    lines = [o.text for o in donor_ops[:report["donor_cut"]]] + report["repair_op_text"] + \
            [o.text for o in host_ops[report["host_cut"]:]]
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"refuse overwrite: {out}")
    kmx = out.with_suffix(".kmx")
    if kmx.exists():
        raise FileExistsError(f"refuse overwrite: {kmx}")
    B.write_kmx(kmx, header, lines)
    circuit = CS.km.Circuit.from_file(str(kmx))
    circuit.to_file(str(out), format="kmb")
    ko, kh, _, kn = CS._ops(out)
    if kh != header or kn > 64 or [o.text for o in ko] != lines:
        raise AssertionError("serialized KMB text mismatch")
    return {"candidate_sha256": sha(out), "candidate_path": str(out),
            "candidate_ops": len(ko), "qubits": kn}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--donor", type=Path, required=True)
    p.add_argument("--host", type=Path, required=True)
    p.add_argument("--donor-sha", required=True)
    p.add_argument("--host-sha", required=True)
    p.add_argument("--out", type=Path, required=True, help="JSON opportunity receipt")
    p.add_argument("--emit", type=Path, help="optional candidate KMB; verifier still required")
    a = p.parse_args(argv)
    if a.out.exists():
        p.error(f"refuse overwrite: {a.out}")
    report, parts = discover(a.donor, a.host, a.donor_sha, a.host_sha)
    if a.emit:
        report["emitted"] = emit(report, parts, a.emit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
