"""Bounded same-width KMB edits; preserves untouched angle/tag packets."""
# Ported from vqcc-research rat_workflow/batch.py (R, Apache-2.0).
from pathlib import Path
import struct
import json
import numpy as np
from .common import K, E, sha
from . import view as V

def stream_edits(k, script, child):
    """Literal same-width edits with unchanged angles/tags, streamed per column.

    Reuse QHDL's parser/counters/map conventions; never allocate output-size
    arrays. Unsupported copies/angle/tag edits explicitly refuse.
    """
    edits = E.parse_script(script, len(k.op_types))
    source = E.Source(k)
    segments, hunks = [], []
    totals = dict.fromkeys(source.cnt, 0)
    newpos, prev = 0, 0
    for edit in edits+[dict(a=len(k.op_types), b=len(k.op_types), ops=[], sentinel=True)]:
        a,b = edit['a'], edit['b']
        olda, oldb = source.at(prev), source.at(a)
        if a > prev:
            segments.append(dict(kind='equal', a=prev, b=a, lo=olda, hi=oldb))
            hunks.append(['equal',prev,a,newpos,newpos+a-prev])
            for key in totals:
                totals[key] += oldb[key]-olda[key]
            newpos += a-prev
        if edit.get('sentinel'):
            break
        oldtypes = k.op_types[a:b] & 127
        if np.any((oldtypes == K.INFO_TAG) | (oldtypes == K.Z_POW)):
            raise ValueError('streaming rule materializer preserves all angle/tag operations')
        rows = edit['ops']
        if any('copy' in r or r.get('angle_from') is not None or r['code'] & 127 in (K.INFO_TAG,K.Z_POW) for r in rows):
            raise ValueError('streaming rule materializer accepts literal non-angle/non-tag edits only')
        if any(q >= int(k.num_qubits) for r in rows for q in r['q']) or any(
            v is not None and v >= int(k.num_bits) for r in rows for v in (r['b0'],r['bc'])):
            raise ValueError('streaming rule materializer requires unchanged declared widths')
        cols = {key:[] for key in E.U32}
        for row in rows:
            code = row['code']
            names = {48:('qqq0','qqq1','qqq2'),32:('qq0','qq1'),16:('q0',)}.get(code & 48,())
            for name,q in zip(names,row['q']):
                cols[name].append(q)
            if code & 64:
                cols['b0'].append(row['b0'])
            if code & 128:
                cols['bc'].append(row['bc'])
        types = np.asarray([r['code'] for r in rows], dtype=np.uint8)
        counts = E.Source.counts(types)
        for key in totals:
            totals[key] += counts[key]
        segments.append(dict(kind='replace', types=types, cols=cols))
        hunks.append(['replace',a,b,newpos,newpos+len(rows)])
        newpos += len(rows)
        prev = b
    prefix = bytearray(k.raw[:k.offsets['op_types'][0]-16])
    struct.pack_into('<9Q',prefix,32,newpos,totals['q3'],totals['q2'],totals['q1'],totals['b0'],totals['bc'],
                     k.counts['angle'], k.counts['info_tags'],k.counts['info_tag_chars'])
    keys = dict(qqq0='q3',qqq1='q3',qqq2='q3',qq0='q2',qq1='q2',q0='q1',b0='b0',bc='bc')
    def copy(f, array):
        # Small write views keep the Python/OS buffering footprint bounded.
        for start in range(0,len(array),262144):
            f.write(memoryview(array[start:start+262144]))
    with Path(child).open('xb') as f:
        f.write(prefix)
        for number,name in enumerate(['op_types']+list(E.U32),1):
            count = newpos if name == 'op_types' else totals[keys[name]]
            f.write(struct.pack('<2Q',number,count*(1 if number == 1 else 4)))
            for seg in segments:
                if seg['kind'] == 'equal':
                    arr = k.op_types[seg['a']:seg['b']] if number == 1 else k.stream(name)[seg['lo'][keys[name]]:seg['hi'][keys[name]]]
                else:
                    arr = seg['types'] if number == 1 else np.asarray(seg['cols'][name], dtype='<u4')
                copy(f,arr)
        # Both metadata streams and their packet headers remain byte identical.
        copy(f,k.raw[k.offsets['angles'][0]-16:])
    return edits,hunks

def materialize(source, script, child):
    k = K.read(str(source))
    edits,hunks = stream_edits(k,script,child)
    fresh = K.read(str(child))
    assert fresh.registers == k.registers and fresh.num_qubits == k.num_qubits and fresh.num_bits == k.num_bits
    old, new = E.Source(k), E.Source(fresh)
    checked, changed = 0, 0
    keys = dict(qqq0='q3', qqq1='q3', qqq2='q3', qq0='q2', qq1='q2', q0='q1', b0='b0', bc='bc')
    for h, edit in zip([x for x in hunks if x[0] != 'equal'], edits):
        assert h[1:3] == [edit['a'], edit['b']]
    for kind,a,b,c,d in hunks:
        oa, ob, na, nb = old.at(a), old.at(b), new.at(c), new.at(d)
        if kind == 'equal':
            assert np.array_equal(k.op_types[a:b], fresh.op_types[c:d])
            for key, counter in keys.items():
                assert np.array_equal(old.src[key][oa[counter]:ob[counter]], new.src[key][na[counter]:nb[counter]])
            assert np.array_equal(old.angles[oa['ang']:ob['ang']], new.angles[na['ang']:nb['ang']])
            assert old.tags[oa['tag']:ob['tag']] == new.tags[na['tag']:nb['tag']]
            checked += b-a
        else:
            edit = next(e for e in edits if e['a'] == a and e['b'] == b)
            want = [V.parse(V.text(dict(r, angle128_le_hex=None, tag_hex=None))) for r in edit['ops']]
            actual = V.window(child, c, d)['records'] if d > c else []
            assert [V.text(r) for r in actual] == [V.text(r) for r in want]
            changed += 1
    return dict(child=str(child), child_sha256=sha(child), unchanged_operations_checked=checked,
                replacements_checked=changed, full_header_register_widths_preserved=True,
                source_ops=len(k.op_types), child_ops=len(fresh.op_types), hunks=hunks,
                scope='Exact edit/map and binary stream checks, not whole-task verifier')
