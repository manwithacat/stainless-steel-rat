#!/usr/bin/env python3
"""Search reached-state physical-product null relations around a CCX target.

Each hit is a *candidate*: adding two entry-wire products that agree modulo
affine terms on a finite legal-x panel may lower the target polynomial rank.
The original target polynomial is exact on arbitrary interval-entry bits;
the null relation is only panel evidence and needs full proof before emission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

from ssr.qhdl import bitsim as B
from ssr.qhdl import window as W
from ssr.rules import quadratic_rank as Q
from ssr.rules import target_accumulation as A


def _column(words: np.ndarray, n: int) -> int:
    return int.from_bytes(words.astype("<u8", copy=False).tobytes(), "little") & ((1 << n) - 1)


class AffineQuotient:
    def __init__(self, features: list[tuple[int, int]], constant: int):
        self.columns = features + [(-1, constant)]
        self.basis: dict[int, tuple[int, int]] = {}
        for i, (_, value) in enumerate(self.columns):
            residual, previous = self.reduce(value)
            if residual:
                self.basis[residual.bit_length() - 1] = (residual, (1 << i) ^ previous)

    def reduce(self, value: int) -> tuple[int, int]:
        combination = 0
        for pivot in sorted(self.basis, reverse=True):
            if (value >> pivot) & 1:
                old, mask = self.basis[pivot]
                value ^= old
                combination ^= mask
        return value, combination

    def relation(self, mask: int) -> list[str]:
        return ["constant_one" if wire == -1 else f"q{wire}"
                for i, (wire, _) in enumerate(self.columns) if (mask >> i) & 1]


def _edge(rows: list[int], a: int, b: int) -> None:
    rows[a] ^= 1 << b
    rows[b] ^= 1 << a


def search(source: Path, handle: str, *, rows: int = 8192,
           outcomes: tuple[str, ...] = ("zero", "7", "101"),
           max_hits: int = 100, beam_width: int = 0) -> dict:
    source = Path(source)
    site = A.resolve(source, handle)
    if not 128 <= rows <= B.MAX_X or not 1 <= len(outcomes) <= 4 or not 0 <= beam_width <= 1000:
        raise ValueError("rows must be 128..MAX_X and 1..4 outcomes")
    if any(o != "zero" and not o.isdecimal() for o in outcomes):
        raise ValueError("outcomes must be zero or integer seeds")
    header, _, ops, nq = Q.load(source)
    xq = [int(line.split()[1][1:]) for line in header if line.startswith("APPEND_TO_REGISTER ")]
    start, end = site["ops"]
    target = site["target"]
    poly, reason = Q.quadratic(ops, start, end, target, nq, W.Liveness(ops).depth,
                               min_ccx=site["products"], phase_transparent=True)
    if reason or poly["rank"] != site["arbitrary_entry_rank"]:
        raise ValueError(f"source-bound symbolic site changed: {reason}")
    panel = np.sort(np.random.default_rng(20261113).choice(B.legal_rows(),
                                                           size=rows, replace=False))
    columns = [0] * nq
    offset = 0
    for outcome in outcomes:
        sim = B.BitSim(ops, rows=panel, num_qubits=nq, x_qubits=xq, outcome=outcome)
        sim.run(stop=start)
        for wire in range(nq):
            if wire != target:
                columns[wire] |= _column(sim.q[wire], rows) << offset
        offset += rows
    quotient = AffineQuotient([(i, columns[i]) for i in range(nq) if i != target],
                              (1 << offset) - 1)
    original_rank = poly["rank"]
    groups: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for a, b in combinations((i for i in range(nq) if i != target), 2):
        residual, affine = quotient.reduce(columns[a] & columns[b])
        groups[residual].append((a, b, affine))
    hits = []
    collision_count = 0
    intermediate = {}
    for group in groups.values():
        for (a, b, am), (c, d, bm) in combinations(group, 2):
            collision_count += 1
            modified = list(poly["H"])
            _edge(modified, a, b)
            _edge(modified, c, d)
            rank = Q.rank(modified)
            if rank < original_rank:
                hits.append({"products": [[a, b], [c, d]],
                             "new_symbolic_rank": rank,
                             "affine_correction": quotient.relation(am ^ bm),
                             "panel_relation_replayed":
                             ((columns[a] & columns[b]) ^ (columns[c] & columns[d]) ^
                              _xor_columns(quotient, am ^ bm)) == 0})
            elif beam_width and rank <= original_rank + 2 and modified != poly["H"]:
                key = tuple(modified)
                score = (rank, sum(row.bit_count() for row in modified),
                         (a, b, c, d))
                previous = intermediate.get(key)
                if previous is None or score < previous[0]:
                    intermediate[key] = (score, ((a, b, am), (c, d, bm)))
    beam = sorted(intermediate.items(), key=lambda item: item[1][0])[:beam_width]
    depth2_checked = 0
    depth2_hits = []
    if beam_width:
        for (first_matrix, (_, first)), (second_matrix, (_, second)) in combinations(beam, 2):
            depth2_checked += 1
            # H xor N1 xor N2 = H1 xor H2 xor H.
            combined = [a ^ b ^ c for a, b, c in zip(first_matrix, second_matrix, poly["H"])]
            rank = Q.rank(combined)
            if rank < original_rank:
                moves = [first, second]
                flat = [term for pair in moves for term in pair]
                affine_mask = 0
                for pair in moves:
                    affine_mask ^= pair[0][2] ^ pair[1][2]
                depth2_hits.append({"new_symbolic_rank": rank,
                                    "null_moves": [[[a, b], [c, d]] for (a, b, _), (c, d, _) in moves],
                                    "affine_correction": quotient.relation(affine_mask),
                                    "panel_relation_replayed":
                                    (_xor_columns(quotient, affine_mask) ^
                                     _xor_columns_product(columns, flat)) == 0})
    hits.sort(key=lambda h: (h["new_symbolic_rank"], h["products"]))
    depth2_hits.sort(key=lambda h: (h["new_symbolic_rank"], h["null_moves"]))
    return {"schema": "ssr-quadratic-null-search/1",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "site_handle": handle, "ops": [start, end], "target": target,
            "original_rank": original_rank, "original_product_floor": original_rank // 2,
            "panel_random_seed": 20261113, "panel_rows_per_outcome": rows,
            "outcomes": list(outcomes),
            "entry_affine_rank": len(quotient.basis),
            "unique_product_residues": len(groups), "collision_pairs_tested": collision_count,
            "hits": hits[:max_hits], "hit_count": len(hits),
            "beam_width": beam_width, "beam_candidates": len(beam),
            "depth2_pairs_checked": depth2_checked,
            "depth2_hits": depth2_hits[:max_hits], "depth2_hit_count": len(depth2_hits),
            "tier": "exact original symbolic polynomial; finite-panel null relation",
            "limits": "a hit needs all legal inputs, all histories and phase proof before KMB emission"}


def _xor_columns(quotient: AffineQuotient, mask: int) -> int:
    value = 0
    for i, (_, column) in enumerate(quotient.columns):
        if (mask >> i) & 1:
            value ^= column
    return value


def _xor_columns_product(columns: list[int], terms: list[tuple[int, int, int]]) -> int:
    value = 0
    for a, b, _ in terms:
        value ^= columns[a] & columns[b]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--handle", required=True)
    parser.add_argument("--rows", type=int, default=8192)
    parser.add_argument("--outcomes", default="zero,7,101")
    parser.add_argument("--beam-width", type=int, default=0,
                        help="bounded two-null-relation beam (0 disables)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refuse to overwrite output")
    try:
        result = search(args.source, args.handle, rows=args.rows,
                        outcomes=tuple(args.outcomes.split(",")), beam_width=args.beam_width)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"hits": result["hit_count"], "depth2_hits": result["depth2_hit_count"],
                      "collision_pairs": result["collision_pairs_tested"],
                      "out": str(args.out)}))


if __name__ == "__main__":
    main()
