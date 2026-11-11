#!/usr/bin/env python3
"""Exact nested cancellation of self-inverse KMB gates on disjoint corridors."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from ssr.qhdl import kmb as K


def scan(path:Path,script:Path|None=None):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
    k=K.read(str(path));t=k.op_types
    s={n:k.stream(n) for n in ('qqq0','qqq1','qqq2','qq0','qq1','q0')}
    n3=n2=n1=0;depth=0
    last=[-1]*k.num_qubits;history={};counts=Counter();first={};deleted=[]
    def barrier():
        history.clear()
        last[:]=[-1]*len(last)
    for op,code0 in enumerate(t):
        code=int(code0);base=code&0x7f
        if code==K.PUSH_CONDITION:
            depth+=1;barrier();continue
        if code==K.POP_CONDITION:
            depth-=1;barrier();continue
        cls=code&0x30;sig=None
        if cls==0x30:
            a,b,c=(int(s[n][n3]) for n in ('qqq0','qqq1','qqq2'))
            n3+=1;wires=(a,b,c)
            if base==0x30:sig=('CCZ',*sorted(wires))
            elif base==0x31:sig=('CCX',*sorted((a,b)),c)
            elif base==0x32:sig=('CSWAP',a,*sorted((b,c)))
        elif cls==0x20:
            a,b=int(s['qq0'][n2]),int(s['qq1'][n2]);n2+=1;wires=(a,b)
            if base==0x20:sig=('CZ',*sorted(wires))
            elif base==0x21:sig=('CX',a,b)
            elif base==0x22:sig=('SWAP',*sorted(wires))
        elif cls==0x10:
            a=int(s['q0'][n1]);n1+=1;wires=(a,)
            if base==0x10:sig=('Z',a)
            elif base==0x11:sig=('X',a)
        else:
            barrier();continue
        if sig is None or depth or code&0x80:
            barrier();continue
        old=last[wires[0]]
        old_record=history.get(old)
        if old_record and old_record[0]==sig and all(last[q]==old for q in wires):
            counts[sig[0]]+=1
            if sig[0] not in first:
                first[sig[0]]={'first':old,'second':op,'signature':sig}
            for q,prev in zip(wires,old_record[1]):last[q]=prev
            del history[old]
            deleted.extend((old,op))
        else:
            prev=tuple(last[q] for q in wires)
            history[op]=(sig,prev)
            for q in wires:last[q]=op
    charged={name:counts[name] for name in ('CCX','CCZ','CSWAP') if counts[name]}
    if script is not None:
        script.write_text(''.join(f'delete {op}\n' for op in sorted(deleted)))
    return {'source_sha256':digest.hexdigest(),'num_ops':len(t),
            'counts':dict(counts),'charged_pairs':charged,'first':first,
            'deleted_ops':len(deleted),
            'decision':'charged candidate needs official verification'
                       if charged else 'no charged candidate under nested exact grammar',
            'tier':'exact commuting involutions, supported unconditional regions only'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('circuit',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--script',type=Path)
    args=ap.parse_args()
    result=scan(args.circuit,args.script)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
