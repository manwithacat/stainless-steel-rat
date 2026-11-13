#!/usr/bin/env python3
"""Find source-bound target-only CCX accumulations for reached-state synthesis.

This is a census, not a rewrite. Arbitrary-entry quadratic rank can be at
the five-product floor even when reached-state relations permit a cheaper
network. A constructor must independently prove its interface and phase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ssr.qhdl import bitsim as B
from ssr.qhdl import window as W
from ssr.rules import quadratic_rank as Q


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def census(source: Path, *, products: int = 5, span: int = 256) -> dict:
    source = Path(source)
    if not 2 <= products <= 8 or not products <= span <= 2048:
        raise ValueError("products must be 2..8 and span products..2048")
    source_sha = _sha(source.read_bytes())
    _, lines, ops, nq = Q.load(source)
    if len(ops) > 200_000 or nq > 256:
        raise ValueError("census cap: 200000 ops, 256 qubits")
    depth = W.Liveness(ops).depth
    writes: dict[int, list[int]] = defaultdict(list)
    for i, op in enumerate(ops):
        if op.code == B.C_CCX and op.cond < 0 and depth[i] == 0:
            writes[op.q[-1]].append(i)
    rows = []
    rejected = defaultdict(int)
    for target, positions in sorted(writes.items()):
        for offset in range(len(positions) - products + 1):
            group = positions[offset:offset + products]
            start, end = group[0], group[-1] + 1
            if end - start > span:
                rejected["span_cap"] += 1
                continue
            poly, reason = Q.quadratic(ops, start, end, target, nq, depth,
                                       min_ccx=products, phase_transparent=True)
            if reason:
                rejected[reason] += 1
                continue
            if poly["ccx"] != products:
                rejected["unexpected_product_count"] += 1
                continue
            # Bind the handle to the actual source bytes and the exact window.
            handle = _sha(json.dumps({"rule": "target-accumulation-v1",
                                      "source_sha256": source_sha,
                                      "ops": [start, end], "text": lines[start:end]},
                                     sort_keys=True).encode())
            rows.append({"handle": handle, "ops": [start, end],
                         "target": target, "products": products,
                         "arbitrary_entry_rank": poly["rank"],
                         "arbitrary_entry_floor": poly["floor"],
                         "footprint_ops": end - start,
                         "quadratic_input_wires": [i for i, row in enumerate(poly["H"]) if row]})
    rows.sort(key=lambda row: (row["ops"][0], row["target"]))
    return {"schema": "ssr-target-accumulation-census/1",
            "source_sha256": source_sha, "declared_qubits": nq,
            "op_count": len(ops), "products": products, "span_cap": span,
            "sites": rows, "site_count": len(rows),
            "rejected": dict(sorted(rejected.items())),
            "evidence": "exact arbitrary-entry symbolic target polynomial and static interface",
            "next": "derive a reached-state interface and synthesize a replacement; census does not certify a gain"}


def resolve(source: Path, handle: str, *, products: int = 5,
            span: int = 256) -> dict:
    """Recompute the census and reject a handle from different source bytes."""
    report = census(source, products=products, span=span)
    match = next((row for row in report["sites"] if row["handle"] == handle), None)
    if match is None:
        raise ValueError("unknown or stale source-bound accumulation handle")
    return match


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--products", type=int, default=5)
    parser.add_argument("--span", type=int, default=256)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refuse to overwrite output")
    try:
        result = census(args.source, products=args.products, span=args.span)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"source_sha256": result["source_sha256"],
                      "site_count": result["site_count"],
                      "rejected": result["rejected"],
                      "report": str(args.out)}))


if __name__ == "__main__":
    main()
