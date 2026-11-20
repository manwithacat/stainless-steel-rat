# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Typed seven-bit delta constraints from ThemBones' RK7/WR7 toolkit.

This independent NumPy checker implements the public relation equations and
int/F/B and composed G/base/block[/low] targets. It does not run a fit, choose an address matching, or prove
that a compiler exploits a relation. A violated relation is not a task failure.
"""
import numpy as np


def parse(text,bits=7,columns=75):
    if type(bits) is not int or not 1<=bits<=8 or columns<10 or columns%5:raise ValueError('invalid relation dimensions')
    out=[]
    for raw in text.splitlines():
        for line in raw.split('#',1)[0].split(';'):
            if not line.strip():continue
            parts=[p.strip() for p in line.split('|')]
            if len(parts)!=3:raise ValueError('relation must be k | j:b ... | target')
            k=int(parts[0]);terms=[tuple(int(v) for v in s.split(':')) for s in parts[1].split()]
            if not 1<=k<columns//5 or not terms or any(len(t)!=2 or not 0<=t[0]<5 or not 0<=t[1]<bits for t in terms):raise ValueError('relation output outside word/slot width')
            if len(set(terms))!=len(terms):raise ValueError('duplicate relation output')
            spec=parse_target(parts[2])
            out.append(dict(loader=k,outputs=[list(t) for t in terms],target=spec))
            if len(out)>4096:raise ValueError('relation budget exceeded')
    return out


def parse_target(text):
    if text.startswith('G/'):
        parts=text.split('/')
        if len(parts) not in (3,4) or parts[1].startswith('G'):raise ValueError('invalid G target')
        base=parse_target(parts[1]);blocks=int(parts[2],16);low=int(parts[3],16) if len(parts)==4 else 0
        if not 0<=blocks<1<<128 or not 0<=low<1<<16:raise ValueError('G table outside address domain')
        return dict(kind='G',base=base,block_bits_hex=hex(blocks),low_bits_hex=hex(low))
    if text.startswith(('F:','B:')):
        kind,value=text.split(':');value=int(value,0)
        if value<0 or value>= (1<<64 if kind=='F' else 16):raise ValueError('target outside supported range')
        return dict(kind=kind,value=value)
    mask=int(text,0)
    if not 0<=mask<2048:raise ValueError('target mask outside address domain')
    return dict(kind='mask',mask=mask)


def parity(values):
    values=np.asarray(values,dtype=np.int64).copy()
    if np.any(values<0):raise ValueError('parity requires nonnegative bit masks')
    result=np.zeros(values.shape,dtype=np.int64)
    while np.any(values):result^=values&1;values>>=1
    return result


def target(spec,addresses):
    a=np.asarray(addresses,dtype=np.int64)
    if np.any(a<0) or np.any(a>=2048):raise ValueError('address outside0..2047')
    kind=spec['kind']
    if kind=='mask':return parity(a&spec['mask'])
    if kind=='G':
        g=int(spec['block_bits_hex'],16)
        low=int(spec['low_bits_hex'],16)
        return target(spec['base'],a)^np.asarray([(g>>int(i))&1 for i in a>>4],np.int64)^np.asarray([(low>>int(i))&1 for i in a&15],np.int64)
    if kind=='B':return np.asarray([(spec['value']>>int(i))&1 if i<4 else 0 for i in a>>4],np.int64)
    if kind=='F':
        rng=np.random.default_rng([spec['value'],5]);f=rng.integers(0,2,16);g=rng.integers(0,2,128)
        return f[a&15]^g[a>>4]
    raise ValueError('unsupported target dialect')


def check(words,relations,bits=7,addresses=None):
    w=np.asarray(words)
    if not np.issubdtype(w.dtype,np.integer) or w.ndim!=2 or not 1<=len(w)<=2048 or w.shape[1]<10 or w.shape[1]%5:
        raise ValueError('integer word matrix with5*Kcolumns and1..2048rows required')
    if type(bits) is not int or not 1<=bits<=8:raise ValueError('unsupported word width')
    if np.any(w<-(1<<(bits-1))) or np.any(w>=(1<<bits)):raise ValueError('word outside declared signed/unsigned width')
    w=np.mod(w.astype(np.int64),1<<bits)
    a=np.arange(len(w),dtype=np.int64) if addresses is None else np.asarray(addresses)
    if not np.issubdtype(a.dtype,np.integer) or a.shape!=(len(w),) or len(np.unique(a))!=len(a):raise ValueError('addresses must be unique integers matching word rows')
    if np.any(a<0) or np.any(a>=2048):raise ValueError('address outside0..2047')
    rows=[];basis={};rank=0
    for j,r in enumerate(relations):
        k=r['loader'];acc=np.zeros(len(w),np.int64);mask=0
        if not 1<=k<w.shape[1]//5:raise ValueError('loader outside word table')
        terms=r['outputs']
        if not terms or len(set(tuple(t) for t in terms))!=len(terms):raise ValueError('empty/duplicate relation output')
        for slot,bit in terms:
            if not 0<=slot<5 or not 0<=bit<bits:raise ValueError('relation output outside word/slot width')
            acc^=((w[:,5*k+slot]^w[:,5*(k-1)+slot])>>bit)&1
            mask^=(1<<((5*k+slot)*bits+bit))^(1<<((5*(k-1)+slot)*bits+bit))
        wrong=np.flatnonzero(acc!=target(r['target'],a))
        v=mask
        while v:
            p=v.bit_length()-1
            if p not in basis:basis[p]=v;rank+=1;break
            v^=basis[p]
        rows.append(dict(index=j,**r,violations=len(wrong),first_addresses=a[wrong[:8]].tolist()))
    n=sum(r['violations'] for r in rows)
    return dict(schema='ssr-chemistry-relations/1',status='CONSTRAINTS_HOLD' if n==0 else 'CONSTRAINTS_VIOLATED',
                word_bits=bits,addresses=len(w),columns=w.shape[1],relation_count=len(rows),relation_rank=rank,
                violated_relation_rows=n,relations=rows,task_admission='NOT_RUN',
                scope='Exact declared delta-word constraints only; not numerical validity, a loader implementation, or a rounding feasibility proof.')
