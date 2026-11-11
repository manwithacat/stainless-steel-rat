#!/usr/bin/env python3
"""Conservative exact disjoint-corridor involution census for KMB circuits."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from ssr.qhdl import kmb as K


def scan(path: Path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
    k = K.read(str(path))
    s = {n:k.stream(n) for n in ('qqq0','qqq1','qqq2','qq0','qq1','q0')}
    t = k.op_types
    n3 = n2 = n1 = 0
    depth = 0
    last_touch = [-1]*k.num_qubits
    prior = {}
    counts = Counter()
    first = {}
    max_span = Counter()
    for op, code0 in enumerate(t):
        code = int(code0); base = code & 0x7f
        if code == K.PUSH_CONDITION:
            depth += 1; prior.clear(); continue
        if code == K.POP_CONDITION:
            depth -= 1; prior.clear(); continue
        cls = code & 0x30
        sig = None
        if cls == 0x30:
            a,b,c = (int(s[n][n3]) for n in ('qqq0','qqq1','qqq2'))
            n3 += 1; wires = (a,b,c)
            if base == 0x30: sig = ('CCZ',*sorted(wires))
            elif base == 0x31: sig = ('CCX',*sorted((a,b)),c)
            elif base == 0x32: sig = ('CSWAP',a,*sorted((b,c)))
        elif cls == 0x20:
            a,b = int(s['qq0'][n2]),int(s['qq1'][n2]); n2 += 1
            wires = (a,b)
            if base == 0x20: sig = ('CZ',*sorted(wires))
            elif base == 0x21: sig = ('CX',a,b)
            elif base == 0x22: sig = ('SWAP',*sorted(wires))
        elif cls == 0x10:
            a = int(s['q0'][n1]); n1 += 1; wires = (a,)
            if base == 0x10: sig = ('Z',a)
            elif base == 0x11: sig = ('X',a)
        else:
            prior.clear(); continue
        if sig is None or depth or code & 0x80:
            prior.clear()
        else:
            old = prior.get(sig)
            if old is not None and all(last_touch[q] == old for q in wires):
                kind = sig[0]
                counts[kind] += 1
                if kind not in first:
                    first[kind] = {'first':old,'second':op,'signature':sig}
                max_span[kind] = max(max_span[kind],op-old)
                prior.pop(sig)
            else:
                prior[sig] = op
        for q in wires: last_touch[q] = op
    charged = {name:counts[name] for name in ('CCX','CCZ','CSWAP')
               if counts[name]}
    return {'source_sha256':digest.hexdigest(),
            'num_ops':len(t),'counts':dict(counts),'first':first,
            'max_span':dict(max_span),'charged_pairs':charged,
            'decision':'charged candidate needs official verification'
                       if charged else 'no charged candidate under this exact grammar',
            'rule':'exact same unconditional involution; no operand touch or barrier between uses'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('circuit',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=scan(args.circuit)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('source_sha256','num_ops','counts','first')}))


if __name__=='__main__': main()
