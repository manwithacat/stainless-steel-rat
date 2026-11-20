# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Chunked lifetime/peak invoice without a full operation-reference graph.

Registers remain pinned. Intervals split only at unconditional top-level R/HMR.
A scratch interval ending at its last touch uses the original task's zero-final
workspace premise. The peak is exact for this conservative interval model,
not a lower bound across different encodings or conditional-zero proofs.
"""
from pathlib import Path
import numpy as np
from .source import K, sha


def intervals(path, chunk_ops=65536, max_intervals=2000000):
    if type(chunk_ops) is not int or not 1 <= chunk_ops <= 1048576:
        raise ValueError('chunk_ops must be1..1048576')
    if type(max_intervals) is not int or not 1 <= max_intervals <= 2000000:
        raise ValueError('max_intervals must be1..2000000')
    path = Path(path)
    bound = sha(path)
    k = K.read(str(path))
    try:
        regs = sorted({q for _,ms in k.registers for isq,q,_ in ms if isq})
        scratch = np.ones(k.num_qubits,dtype=bool)
        scratch[regs] = False
        begin = [None] * k.num_qubits
        last = [-1] * k.num_qubits
        ended = [[] for _ in range(k.num_qubits)]
        counters = [0,0,0]
        streams = [tuple(k.stream(n) for n in names) for names in
                   [('qqq0','qqq1','qqq2'),('qq0','qq1'),('q0',)]]
        depth = 0
        number = 0
        for lo in range(0,len(k.op_types),chunk_ops):
            chunk = k.op_types[lo:lo+chunk_ops]
            changes = np.cumsum((chunk == K.PUSH_CONDITION).astype(np.int32) -
                                (chunk == K.POP_CONDITION).astype(np.int32))
            if len(changes) and depth+int(changes.min()) < 0:
                raise ValueError('unbalanced condition stack')
            depths = changes+depth
            depth = int(depths[-1]) if len(depths) else depth
            qs, positions, reset = [], [], []
            for slot,arity in enumerate([0x30,0x20,0x10]):
                ids = np.flatnonzero((chunk & 0x30) == arity)
                start = counters[slot]
                stop = start+len(ids)
                for column in streams[slot]:
                    values = column[start:stop]
                    if len(values) and int(values.max()) >= k.num_qubits:
                        raise ValueError('source qubit outside header')
                    mask = scratch[values]
                    qs.append(values[mask])
                    positions.append(ids[mask]+lo)
                    if arity == 0x10:
                        types = chunk[ids]
                        reset.append(((types[mask] == K.HMR) | (types[mask] == K.R)) &
                                     (depths[ids[mask]] == 0))
                    else:
                        reset.append(np.zeros(int(mask.sum()),dtype=bool))
                counters[slot] = stop
            qq = np.concatenate(qs)
            op = np.concatenate(positions)
            rr = np.concatenate(reset)
            if not len(qq):
                continue
            order = np.lexsort((op,qq))
            qq,op,rr = qq[order],op[order],rr[order]
            starts = np.r_[0,np.flatnonzero(qq[1:] != qq[:-1])+1]
            stops = np.r_[starts[1:],len(qq)]
            for left,right in zip(starts,stops):
                q = int(qq[left])
                touches = op[left:right]
                if begin[q] is None:
                    begin[q] = int(touches[0])
                resets = np.flatnonzero(rr[left:right])
                for r in resets:
                    at = int(touches[r])
                    ended[q].append((begin[q],at,'reset'))
                    number += 1
                    if number > max_intervals:
                        raise ValueError('UNKNOWN_INTERVAL_BUDGET')
                    begin[q] = int(touches[r+1]) if r+1 < len(touches) else None
                last[q] = int(touches[-1])
        if depth:
            raise ValueError('unbalanced condition stack')
        values = []
        for q,rows in enumerate(ended):
            if begin[q] is not None:
                rows.append((begin[q],last[q],'last-touch'))
            values += [(q,s,e,kind) for s,e,kind in rows]
        if len(values) > max_intervals:
            raise ValueError('UNKNOWN_INTERVAL_BUDGET')
        return dict(source_sha256=bound, num_ops=len(k.op_types), num_qubits=k.num_qubits,
                    registers=regs, intervals=values, chunk_ops=chunk_ops,
                    model='pinned registers; unconditional top-level reset or final scratch touch',
                    premise='unnamed scratch starts zero and last-touch retirement assumes it ends zero on the relevant task support',
                    is_global_width_lower_bound=False)
    finally:
        k.raw._mmap.close()
        if sha(path) != bound:
            raise ValueError('source changed during lifetime census')


def invoice(path, chunk_ops=65536, max_intervals=2000000):
    data = intervals(path,chunk_ops,max_intervals)
    iv = data['intervals']
    if not data['num_ops']:
        return dict(data, peak=len(data['registers']), peak_segments=[], peak_runs=[],
                    peak_operations=0, first_peak_scratch=[])
    starts = np.asarray([v[1] for v in iv],dtype=np.int64)
    ends = np.asarray([v[2]+1 for v in iv],dtype=np.int64)
    events = np.r_[starts,ends,0,data['num_ops']]
    delta = np.r_[np.ones(len(iv),np.int32),-np.ones(len(iv),np.int32),0,0]
    order = np.argsort(events,kind='stable')
    events,delta = events[order],delta[order]
    groups = np.r_[0,np.flatnonzero(events[1:] != events[:-1])+1]
    points = events[groups]
    changes = np.add.reduceat(delta,groups)
    width = np.cumsum(changes)+len(data['registers'])
    assert width[-1] == len(data['registers'])
    valid = points < data['num_ops']
    peak = int(width[valid].max())
    segments = [[int(points[i]),int(points[i+1])] for i in range(len(points)-1)
                if points[i] < points[i+1] and width[i] == peak]
    runs = []
    for a,b in segments:
        if runs and runs[-1][1] == a:
            runs[-1][1] = b
        else:
            runs.append([a,b])
    first = segments[0][0]
    live = [dict(wire=q,start=s,stop=e+1,retirement=kind)
            for q,s,e,kind in iv if s <= first <= e]
    data.update(peak=peak, peak_segments=segments, peak_runs=runs,
                peak_operations=sum(b-a for a,b in segments),
                first_peak_scratch=live,
                direct_recolour_may_reduce_header=peak<data['num_qubits'])
    return data
