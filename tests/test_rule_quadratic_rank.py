#!/usr/bin/env python3
"""Arbitrary-entry checks for the constructive quadratic-rank rule."""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

from support import need_kickmix
km = need_kickmix()
from ssr.rules import quadratic_rank as R


def run(lines, x, n=5):
    q = [(x >> i) & 1 for i in range(n)]
    for s in lines:
        t = s.split()
        w = [int(a[1:]) for a in t[1:]]
        if t[0] == "X":
            q[w[0]] ^= 1
        elif t[0] == "CX":
            q[w[1]] ^= q[w[0]]
        elif t[0] == "SWAP":
            q[w[0]], q[w[1]] = q[w[1]], q[w[0]]
        elif t[0] == "CCX":
            q[w[2]] ^= q[w[0]] & q[w[1]]
        else:
            raise ValueError(s)
    return tuple(q)


def run_phase(lines, x, m):
    q = [(x >> i) & 1 for i in range(6)]
    b = {}
    sign = 0
    for s in lines:
        t = s.split()
        gate = t[0]
        if gate == "HMR":
            w = int(t[1][1:]); b[t[2]] = m; sign ^= q[w] & m; q[w] = 0
            continue
        if gate == "CZ":
            a, c = int(t[1][1:]), int(t[2][1:])
            sign ^= q[a] & q[c] & (b[t[4]] if len(t) == 5 else 1)
            continue
        w = [int(a[1:]) for a in t[1:]]
        if gate == "X": q[w[0]] ^= 1
        elif gate == "CX": q[w[1]] ^= q[w[0]]
        elif gate == "CCX": q[w[2]] ^= q[w[0]] & q[w[1]]
        else: raise ValueError(s)
    return tuple(q), sign, tuple(sorted(b.items()))


def main():
    rng = random.Random(20261111)
    total = positive = 0
    for _ in range(200):
        lines = []
        for _ in range(rng.randint(2, 5)):
            for _ in range(rng.randint(0, 5)):
                kind = rng.choice(("X", "CX", "SWAP"))
                if kind == "X":
                    lines.append(f"X q{rng.randrange(5)}")
                else:
                    if kind == "SWAP":
                        a, b = rng.sample(range(4), 2)
                    else:
                        a = rng.randrange(4)
                        b = rng.choice([i for i in range(5) if i != a])
                    lines.append(f"{kind} q{a} q{b}")
            a, b = rng.sample(range(4), 2)
            lines.append(f"CCX q{a} q{b} q4")
        ops = [R.B.parse_line(s) for s in lines]
        poly, reason = R.quadratic(ops, 0, len(ops), 4, 5, [0] * len(ops))
        assert reason is None
        total += 1
        if poly["saving"] <= 0:
            continue
        try:
            rec, reason = R.recipe(ops, 0, len(ops), 4, 5, [0] * len(ops))
        except AssertionError:
            print("failing source:", lines)
            print("failing polynomial:", poly)
            raise
        assert reason is None and rec["saving"] > 0
        assert all(run(lines, x) == run(rec["ops"], x) for x in range(32))
        positive += 1
    assert positive >= 10

    phased = ["CCX q0 q1 q4", "HMR q5 b0", "CZ q0 q2 if b0", "CCX q0 q2 q4"]
    ph_ops = [R.B.parse_line(s) for s in phased]
    p, why = R.quadratic(ph_ops, 0, len(ph_ops), 4, 6, [0] * len(ph_ops),
                         phase_transparent=True)
    assert why is None and p["saving"] == 1
    altered, why = R.recipe(ph_ops, 0, len(ph_ops), 4, 6, [0] * len(ph_ops),
                            phase_transparent=True)
    assert why is None and all(run_phase(phased, x, m) == run_phase(altered["ops"], x, m)
                               for x in range(64) for m in range(2))
    for bad in (["CCX q0 q1 q4", "HMR q4 b0", "CCX q0 q2 q4"],
                ["CCX q0 q1 q4", "CZ q4 q2", "CCX q0 q2 q4"]):
        o = [R.B.parse_line(s) for s in bad]
        _, why = R.quadratic(o, 0, len(o), 4, 6, [0] * len(o), phase_transparent=True)
        assert why in ("target_measured_or_reset", "target_phase_operand")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "source.kmb"
        km.Circuit("CCX q0 q1 q3\nCCX q0 q2 q3\n").to_file(str(source), format="kmb")
        scan = R.census(source)
        assert len(scan["hits"]) == 1 and scan["hits"][0]["saving"] == 1
        child = root / "child.kmb"
        R.emit(source, child, scan["hits"][0]["handle"])
        a = str(km.Circuit.from_file(str(source))).splitlines()
        b = str(km.Circuit.from_file(str(child))).splitlines()
        assert all(run(a, x, 4) == run(b, x, 4) for x in range(16))
        assert sum(s.startswith("CCX") for s in a) == 2
        assert sum(s.startswith("CCX") for s in b) == 1
        stale = root / "stale.kmb"
        km.Circuit("X q0\nCCX q0 q1 q3\nCCX q0 q2 q3\n").to_file(str(stale), format="kmb")
        try:
            R.emit(stale, root / "bad.kmb", scan["hits"][0]["handle"])
        except ValueError as e:
            assert "stale" in str(e)
        else:
            raise AssertionError("stale source-bound handle accepted")
    print(f"PASS: {total} seeded circuits, {positive} positive rewrites x 32 arbitrary states; phase fixture 64 entries x 2 outcomes; fixture 2->1 and stale-handle refusal")


def test_quadratic_rank_seeded_stress_and_fixtures():
    main()


if __name__ == "__main__":
    main()
