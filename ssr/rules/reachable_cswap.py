"""Source-independent exact-input, sampled-branch CSWAP no-op census."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import kickmix as km

from ssr.qhdl import bitsim as B


def _ops(path):
    circuit = km.Circuit.from_file(path)
    lines = str(circuit).splitlines()
    header = [line for line in lines if line.split()[0] in {"APPEND_TO_REGISTER", "REGISTER"}]
    xq = [int(line.split()[1][1:]) for line in header if line.startswith("APPEND_TO_REGISTER")]
    ops = [B.parse_line(line) for line in lines if line.split()[0] not in {"APPEND_TO_REGISTER", "REGISTER"}]
    return ops, header, xq, int(circuit.num_qubits)


def census(path: Path, outcomes=("zero", 7, 101), cache_root: Path | None = None) -> dict:
    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    key = hashlib.sha256((sha + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                          + hashlib.sha256(Path(B.__file__).read_bytes()).hexdigest()
                          + repr(outcomes)).encode()).hexdigest()
    if cache_root is not None:
        cache = Path(cache_root) / f"{key}.json"
        if cache.exists():
            return json.loads(cache.read_text())
    ops, header, xq, qmax = _ops(path)
    depth = 0
    indices = []
    for i, op in enumerate(ops):
        if op.code == B.C_PUSH:
            depth += 1
        elif op.code == B.C_POP:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced condition stack")
        elif op.code == B.C_CSWAP and depth == 0 and op.cond < 0:
            indices.append(i)
    if depth:
        raise ValueError("unbalanced condition stack")
    branch_hits = {}
    for branch in outcomes:
        hits = []
        sim = B.BitSim(ops, num_qubits=qmax, x_qubits=xq, outcome=branch)

        def inspect(i, state):
            op = ops[i]
            control, left, right = op.q
            delta = state.q[control] & (state.q[left] ^ state.q[right])
            if state.act is not None:
                delta &= state.act
            if op.cond >= 0:
                delta &= state._bit(op.cond)
            if not delta.any():
                hits.append(i)

        sim.run(snaps=indices, on_snap=inspect)
        branch_hits[str(branch)] = hits
    shared = set(indices)
    for hits in branch_hits.values():
        shared.intersection_update(hits)
    sites = []
    for i in sorted(shared):
        op = ops[i]
        handle = hashlib.sha256(json.dumps({"source_sha256": sha, "op": i,
                                             "syntax": op.text, "rule": "reachable-cswap-v1"},
                                            sort_keys=True).encode()).hexdigest()
        sites.append({"op": i, "syntax": op.text, "handle": handle,
                      "evidence": "exact all legal x in zero/7/101 branches; all other outcomes unproved"})
    result = {"source_sha256": sha, "Q": qmax, "ops": len(ops),
              "unconditional_cswap_count": len(indices),
              "branch_noop_count": {k: len(v) for k, v in branch_hits.items()},
              "shared_noop_count": len(sites), "sites": sites}
    if cache_root is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, indent=2) + "\n")
    return result


def delete(path: Path, handle: str, out: Path, *, found: dict | None = None) -> dict:
    """One SHA-bound deletion; caller must run native and verifier gates."""
    path, out = Path(path), Path(out)
    found = found if found is not None else census(path)
    if found["source_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("stale source census")
    site = next((s for s in found["sites"] if s["handle"] == handle), None)
    if site is None:
        raise ValueError("unknown, stale or unverified CSWAP handle")
    if out.exists():
        raise ValueError("candidate path exists")
    ops, header, _, _ = _ops(path)
    del ops[site["op"]]
    candidate = km.Circuit("\n".join(header + [op.text for op in ops]) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    candidate.to_file(out, format="kmb")
    return {"source_sha256": found["source_sha256"], "candidate": str(out),
            "candidate_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "removed": site, "proofscope": "all legal x in three branch draws; native gate required"}
