#!/usr/bin/env python3
"""Portable HMR panel/order/skip reproducibility fixtures."""

import sys
from pathlib import Path

import numpy as np

from ssr.rules.portable_hmr import B,PortableBitSim


def record(sim):
    n=len(sim.rows)
    return {int(x):(
        tuple(int(B.unpack_bits(sim.q[q],n)[r]) for q in range(sim.nq)),
        tuple((b,int(B.unpack_bits(v,n)[r])) for b,v in sorted(sim.bits.items())),
        int(B.unpack_bits(sim.sign,n)[r]),int(sim.rot[r]))
        for r,x in enumerate(sim.rows)}


def main():
    ops=[B.parse_line(s) for s in (
        'HMR q0 b0','HMR q1 b1 if b0','HMR q2 b2',
        'X q2 if b2','CZ q1 q2 if b0','Z q1 if b1')]
    xs=np.arange(1,65,dtype=np.int64)
    def run(rows,seed):
        return PortableBitSim(ops,seed=seed,rows=np.array(rows,dtype=np.int64),
                              num_qubits=3,x_qubits=[0,1]).run()
    full=record(run(xs,17))
    first={x:v[1][0][1] for x,v in full.items()}
    x0=next(x for x in xs if first[int(x)]==0)
    x1=next(x for x in xs if first[int(x)]==1)
    small=record(run([x0],17));mixed=record(run([x1,x0],17))
    assert small[int(x0)]==full[int(x0)]==mixed[int(x0)]
    assert mixed[int(x1)]==full[int(x1)]
    assert all(record(run(xs[::-1],17))[x]==full[x] for x in full)
    other=record(run(xs,18))
    assert any(other[x]!=full[x] for x in full)
    # The second HMR is globally skipped on [x0] but executes on [x1,x0].
    assert small[int(x0)][1][1][1]==0
    print({'panel_order_same':True,'globally_skipped_hmr_stable':True,
           'different_seed_changes_history':True,'overlap_rows':[int(x0),int(x1)]})

def test_portable_hmr_panel_order_and_skip_stability():
    main()


if __name__=='__main__':main()
