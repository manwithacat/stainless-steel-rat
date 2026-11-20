# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Exact syntactic product loans; a census, not a joint rewrite or task gate.

Zero entry is the named-register task ABI, not a property of an arbitrary KMB.
Write versions deliberately forget a formula when its controls change, even
if a later gate could restore them. No sampled/hash-based equality is used.
"""
from bisect import bisect_right
from pathlib import Path
import numpy as np
from .source import K,sha
Z,X,CZ,CX,CCZ,CCX,CSWAP = 0x10,0x11,0x20,0x21,0x30,0x31,0x32


def quantum_events(k, chunk_ops=65536):
    streams=[tuple(k.stream(n) for n in ns) for ns in
             [('q0',),('qq0','qq1'),('qqq0','qqq1','qqq2')]]
    counters=[0,0,0];depth=0
    for lo in range(0,len(k.op_types),chunk_ops):
        t=k.op_types[lo:lo+chunk_ops]
        changes=np.cumsum((t==K.PUSH_CONDITION).astype(np.int32)-(t==K.POP_CONDITION).astype(np.int32))
        depths=depth+changes
        if len(depths) and depths.min()<0:raise ValueError('unbalanced condition stack')
        depth=int(depths[-1]) if len(depths) else depth
        arity=(t & 0x30)>>4
        ids=np.flatnonzero(arity)
        cols=np.full((len(t),3),-1,dtype=np.int32)
        for j in range(3):
            at=np.flatnonzero(arity==j+1);start=counters[j];stop=start+len(at)
            for c,v in enumerate(streams[j]):cols[at,c]=v[start:stop]
            counters[j]=stop
        for i in ids:
            code=int(t[i]);qs=tuple(int(v) for v in cols[i,:int(arity[i])])
            if min(qs)<0 or max(qs)>=k.num_qubits:raise ValueError('qubit outside header')
            yield lo+int(i),code&127,qs,bool(code&128 or depths[i]),int(depths[i])
    if depth:raise ValueError('unbalanced condition stack')


def census(path, peaks, max_handles=100000):
    if type(max_handles) is not int or not 1<=max_handles<=1000000:raise ValueError('invalid handle budget')
    peaks=[(int(a),int(b)) for a,b in peaks]
    if any(a<0 or b<=a or (j and a<peaks[j-1][1]) for j,(a,b) in enumerate(peaks)):
        raise ValueError('invalid peak ranges')
    ends=[b for a,b in peaks]
    path=Path(path);bound=sha(path);k=K.read(str(path))
    try:
        pinned={q for _,ms in k.registers for isq,q,_ in ms if isq}
        versions=[0]*k.num_qubits
        forms=[None if q in pinned else False for q in range(k.num_qubits)]
        last=[-1]*k.num_qubits;last_depth=[0]*k.num_qubits
        handles=[];events=0
        def value(q):
            f=forms[q]
            if isinstance(f,tuple) and (versions[f[0]]!=f[2] or versions[f[1]]!=f[3]):return None
            return f
        def setv(q,v):
            versions[q]+=1;forms[q]=v
        def xor(a,b):
            if a is None or b is None:return None
            if isinstance(a,bool) and isinstance(b,bool):return a^b
            if a is False:return b
            if b is False:return a
            if a is True:return (*b[:4],not b[4])
            if b is True:return (*a[:4],not a[4])
            if a[:4]==b[:4]:return a[4]^b[4]
            return None
        for at,code,qs,guarded,depth in quantum_events(k):
            events+=1
            # Inspect the idle interval BEFORE this operation changes a value.
            for q in set(qs):
                f=value(q);a=last[q]+1;b=at
                j=bisect_right(ends,a)
                if (q not in pinned and isinstance(f,tuple) and depth==0 and last_depth[q]==0
                    and a<b and j<len(peaks) and peaks[j][0]<b):
                    handles.append(dict(wire=q,start=a,stop=b,controls=list(f[:2]),
                                        control_write_versions=list(f[2:4]),constant=int(f[4]),
                                        previous_touch=last[q],next_touch=at,
                                        first_peak_overlap=max(a,peaks[j][0]),rebuild_Toffolis=1,
                                        extra_quantum_wires=0,extra_private_classical_bits=1,
                                        proof='zero-entry product or exact copy/inversion; controls never written; target idle; top-level cuts'))
                    if len(handles)>max_handles:raise ValueError('UNKNOWN_HANDLE_BUDGET')
            if code in (Z,K.Z_POW,CZ,CCZ):pass
            elif code in (K.R,K.HMR):
                q=qs[0];old=value(q)
                setv(q,False if not guarded or old is False else None)
            elif code==X:
                q=qs[0];setv(q,None if guarded else xor(value(q),True))
            elif code==CX:
                a,b=qs
                if a==b:raise ValueError('aliased CX operands')
                va,vb=value(a),value(b)
                if va is not False:setv(b,None if guarded else xor(vb,va))
            elif code==CCX:
                a,b,c=qs
                if len(set(qs))!=3:raise ValueError('aliased CCX operands')
                va,vb,vc=value(a),value(b),value(c)
                if va is not False and vb is not False:
                    if guarded:p=None
                    elif va is True:p=vb
                    elif vb is True:p=va
                    else:
                        a,b=sorted((a,b));p=(a,b,versions[a],versions[b],False)
                    setv(c,xor(vc,p))
            elif code==K.SWAP:
                a,b=qs;va,vb=value(a),value(b)
                if not guarded:setv(a,vb);setv(b,va)
                elif va is not False or vb is not False:setv(a,None);setv(b,None)
            elif code==CSWAP:
                a,b,c=qs;va,vb,vc=value(a),value(b),value(c)
                if va is not False and (vb is not False or vc is not False):
                    if va is True and not guarded:setv(b,vc);setv(c,vb)
                    else:setv(b,None);setv(c,None)
            else:
                for q in qs:setv(q,None)
            for q in set(qs):last[q]=at;last_depth[q]=depth
        return dict(schema='ssr-product-loan-census/1',source_sha256=bound,handles=handles,
                    quantum_events=events,peak_run_count=len(peaks),task_admission='NOT_RUN',
                    assumptions='unnamed scratch initialized zero; named quantum registers arbitrary',
                    scope='Each handle separately proves a product loan. Joint scheduling and recolouring are NOT proved.',
                    repair='HMR w -> fresh m; CZ(a,b) if m; NEG if m when constant=1; CCX(a,b,w) and optional X before next touch')
    finally:
        k.raw._mmap.close()
        if sha(path)!=bound:raise ValueError('source changed during product census')
