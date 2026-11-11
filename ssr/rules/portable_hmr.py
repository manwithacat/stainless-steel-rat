"""Panel-stable HMR histories for R-side reject-only BitSim screens.

Outcome bit = SplitMix64(seed, source operation index, legal input x) high bit.
This is an additional deterministic stress model, not KickMix's verifier RNG.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from ssr.qhdl import bitsim as B  # noqa: E402


class IndexedOps(list):
    def __init__(self,ops):
        super().__init__(ops)
        self.current_index=None

    def __getitem__(self,index):
        if isinstance(index,int):self.current_index=index
        return super().__getitem__(index)


class PortableBitSim(B.BitSim):
    """BitSim whose HMR outcomes for each (seed, op, x) survive panel changes."""

    def __init__(self,ops,*,seed:int,**kwargs):
        self.portable_seed=int(seed)
        indexed=IndexedOps(ops)
        super().__init__(indexed,outcome=0,**kwargs)

    def _outcome(self):
        op_index=self.ops.current_index
        if op_index is None or self.ops[op_index].code!=B.C_HMR:
            raise RuntimeError('portable HMR draw has no source operation index')
        with np.errstate(over='ignore'):
            z=(self.rows.astype(np.uint64)*np.uint64(0xD6E8FEB86659FD93))
            z^=np.uint64(self.portable_seed)
            z^=np.uint64(op_index+1)*np.uint64(0x9E3779B97F4A7C15)
            z=(z+np.uint64(0x9E3779B97F4A7C15))
            z=(z^(z>>np.uint64(30)))*np.uint64(0xBF58476D1CE4E5B9)
            z=(z^(z>>np.uint64(27)))*np.uint64(0x94D049BB133111EB)
            z^=z>>np.uint64(31)
        return B.pack_bits((z>>np.uint64(63)).astype(bool))&self.valid
