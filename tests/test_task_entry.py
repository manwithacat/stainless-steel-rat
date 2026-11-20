"""Portable agent CLI workflow, actual support boundaries and stale-source faults."""
import argparse
import itertools
import json
from pathlib import Path
import numpy as np
import pytest
from ssr.tasks import cli, source
from ssr.qhdl import edit as E


def write_program(path, lines, registers, nq, nb=0):
    ops = [E.parse_op(s) for s in lines]
    streams = {n:[] for n in ['qqq0','qqq1','qqq2','qq0','qq1','q0','b0','bc']}
    for op in ops:
        for n,v in zip({0x30:['qqq0','qqq1','qqq2'],0x20:['qq0','qq1'],0x10:['q0']}.get(op['code']&0x30,[]),op['q']):
            streams[n].append(v)
        if op['b0'] is not None:
            streams['b0'].append(op['b0'])
        if op['bc'] is not None:
            streams['bc'].append(op['bc'])
    source.K.write_kmb(path, [op['code'] for op in ops], streams, registers=registers, num_qubits=nq, num_bits=nb)


def chemistry_fixture(tmp, width):
    registers = [('selection',[(True,j) for j in range(3)])]
    ws = []
    for j in range(5):
        ids = list(range(3+j*width,3+(j+1)*width))
        ws.append(ids)
        registers.append(('word_'+str(j),[(True,q) for q in ids]))
    words = np.zeros((8,10),dtype=np.int64)
    for a in range(8):
        x,y,z = [(a>>j)&1 for j in range(3)]
        for d in range(2):
            words[a,5*d] = (x&y)^d
            words[a,5*d+1] = (z&y)^d
            words[a,5*d+2] = 2*(x^(d*((x^z)&y)))
    npz = tmp/'words.npz'
    np.savez(npz,angle_words=words)
    lines = [f'CX q2 q0',f'CCX q0 q1 q{ws[2][1]}','CX q2 q0',
             f'X q{ws[0][0]}',f'X q{ws[1][0]}']
    kmb = tmp/'source.kmb'
    write_program(kmb,lines,registers,3+5*width)
    return kmb,npz,words,ws


def args(**kw):
    return argparse.Namespace(**kw)


@pytest.mark.parametrize('width',[7,8])
def test_agent_current_function_workflow_and_wrong_bindings(tmp_path,width):
    kmb,npz,words,ws = chemistry_fixture(tmp_path,width)
    scan = tmp_path/'scan'
    r = cli.scan(args(source=str(kmb),task='chemistry',words=str(npz),slot=1,
                      rule='supplied',out=str(scan),max_events=64))
    assert r['handles'] == 1 and r['task_admission'] == 'NOT_RUN'
    hfile = scan/'handle-0.json'
    h = json.loads(hfile.read_text())
    assert h['candidate']['at'] == 1
    proof = cli.construct(args(source=str(kmb),handle=str(hfile),words=str(npz),
                               out=str(tmp_path/'build'),emit_child=str(tmp_path/'child.kmb')))
    assert proof['obligations'] == 'reproved' and proof['task_admission'] == 'PENDING'
    old = source.K.read(str(kmb))
    child = source.K.read(str(tmp_path/'child.kmb'))
    assert len(child.op_types) == len(old.op_types)+1
    assert np.count_nonzero(child.op_types == 0x31) == 0
    assert old.num_qubits == child.num_qubits
    # Independent direct simulation of every forward/reverse actual support row.
    for d,a in itertools.product(range(2),range(8)):
        initial = [a>>j&1 for j in range(3)]+[0]*(5*width)
        for j in range(5):
            for bit,q in enumerate(ws[j]):
                initial[q] = int(words[a,5*d+j])>>bit&1
        results=[]
        for k in [old,child]:
            q=initial.copy()
            for row in source.operations(k):
                if row['name']=='X':
                    q[row['q'][0]]^=1
                elif row['name']=='CX':
                    x,y=row['q'];q[y]^=q[x]
                else:
                    x,y,z=row['q'];q[z]^=q[x]&q[y]
            results.append(q)
        assert results[0] == results[1]
        for j in range(5):
            assert sum(results[1][q]<<bit for bit,q in enumerate(ws[j])) == int(words[a,5*(1-d)+j])
    changed=words.copy();changed[0,5]^=1
    np.savez(tmp_path/'wrong.npz',angle_words=changed)
    with pytest.raises(ValueError,match='word-file binding'):
        cli.construct(args(source=str(kmb),handle=str(hfile),words=str(tmp_path/'wrong.npz'),
                           out=str(tmp_path/'bad-words'),emit_child=None))
    # Re-sealing a forged handle must not turn false geometry into a theorem.
    bad=json.loads(hfile.read_text());bad['candidate']['replacement']=[];bad['id']=cli.seal(bad)
    (tmp_path/'forged.json').write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        cli.construct(args(source=str(kmb),handle=str(tmp_path/'forged.json'),words=str(npz),
                           out=str(tmp_path/'bad-proof'),emit_child=None))
    with pytest.raises(FileExistsError):
        cli.scan(args(source=str(kmb),task='chemistry',words=str(npz),slot=1,
                      rule='supplied',out=str(scan),max_events=64))
    old.raw._mmap.close();child.raw._mmap.close()


def test_quick_census_emits_charged_event_after_free_noise(tmp_path):
    path=tmp_path/'source.kmb'
    regs=[('input',[(True,0),(True,1)])]
    # Free zero-controlled CXs must not consume the charged-candidate event cap.
    lines=['CX q3 q4']*70+['CCX q0 q3 q2']
    write_program(path,lines,regs,5)
    r=cli.quick(path,1)
    zero=[h for h in r['handles'] if h['rule']=='initialized-zero']
    assert len(zero)==1 and zero[0]['event']['op']==70
    h=tmp_path/'handle.json';h.write_text(json.dumps(zero[0]))
    cli.construct(args(source=str(path),handle=str(h),words=None,out=str(tmp_path/'built'),
                       emit_child=str(tmp_path/'child.kmb')))
    child=source.K.read(str(tmp_path/'child.kmb'))
    assert len(child.op_types)==70
    child.raw._mmap.close()
    # Source bytes dominate a remembered address.
    write_program(path,lines+['X q0'],regs,5)
    with pytest.raises(ValueError,match='stale'):
        cli.construct(args(source=str(path),handle=str(h),words=None,out=str(tmp_path/'stale'),emit_child=None))


def test_task_context_prices_width_without_inventing_mean_cost(tmp_path):
    p=tmp_path/'dqi.kmb'
    write_program(p,['CCX q0 q1 q2'],[('syndrome',[(True,0),(True,1)])],901)
    r=cli.context(args(source=str(p),task='dqi',words=None))
    t=next(x for x in r['width_trade'] if x['target_Q']==889)
    assert t['maximum_Toffoli_factor_at_fixed_failure_factor']==pytest.approx((901/889)**2)
    assert r['sources'][0]['expected_charge'] is None and r['task_admission']=='NOT_RUN'
    assert r['sources'][0]['static_charged_instructions']==1


def test_endpoint_parent_mismatch_is_not_an_optimization_negative(tmp_path):
    p,z,w,ws=chemistry_fixture(tmp_path,7)
    w[0,5]^=1
    np.savez(z,angle_words=w)
    with pytest.raises(ValueError,match='parent does not implement'):
        cli.supplied_scan(p,z,1)


def test_scalar_decoder_preserves_captured_condition_operations(tmp_path):
    p=tmp_path/'conditions.kmb'
    write_program(p,['PUSH_CONDITION if b0','HMR q2 b0','POP_CONDITION'],
                  [('input',[(True,0),(True,1)])],3,1)
    k=source.K.read(str(p))
    assert [r['name'] for r in source.operations(k)]==['PUSH_CONDITION','HMR','POP_CONDITION']
    assert source.profile(p)['maximum_condition_depth']==1
    k.raw._mmap.close()
