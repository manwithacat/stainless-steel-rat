"""Streaming profiles match the existing dense definition, including chunk edges."""
import numpy as np
import pytest
from ssr.tasks import liveness as S
from ssr.qhdl import lifetime_allocator as A
from test_task_entry import write_program


def dense(path):
    k=A.K.read(str(path))
    resets,depth=A.reset_ops(k)
    ops,qs,order,_=A.references(k)
    iv=A.build_intervals(k,ops,qs,order,resets)
    p=A.live_profile(iv,len(k.op_types),A.register_qubits(k))
    k.raw._mmap.close()
    return p


def test_unconditional_resets_last_touch_and_pinned_register(tmp_path):
    p=tmp_path/'source.kmb'
    lines=['CX q0 q1','HMR q1 b0','CX q0 q2','CX q0 q2',
           'PUSH_CONDITION if b0','X q3','HMR q3 b0','POP_CONDITION','X q3']
    write_program(p,lines,[('input',[(True,0)])],4,1)
    expected=dense(p)
    for chunk in [1,2,3,7,65536]:
        r=S.invoice(p,chunk)
        actual=np.zeros(len(lines),dtype=int)
        for q,s,e,kind in r['intervals']:
            actual[s:e+1]+=1
        actual+=1
        assert np.array_equal(actual,expected)
        assert r['peak']==int(expected.max())
        assert sum(b-a for a,b in r['peak_segments'])==int(np.count_nonzero(expected==expected.max()))
        # Conditional HMR must not claim a top-level zero boundary.
        assert not any(q==3 and e==6 and kind=='reset' for q,s,e,kind in r['intervals'])


def test_large_chunk_edge_and_ignored_idle_register(tmp_path):
    p=tmp_path/'source.kmb'
    lines=['CX q0 q1']*65535+['HMR q1 b0','CX q0 q2','HMR q2 b0']
    write_program(p,lines,[('input',[(True,0),(True,3)])],4,1)
    r=S.invoice(p,65536)
    expected=dense(p)
    assert r['peak']==int(expected.max())==3
    assert len(r['intervals'])==2
    assert r['registers']==[0,3]


def test_unbalanced_and_budget_are_explicit_unknown(tmp_path):
    p=tmp_path/'source.kmb'
    write_program(p,['HMR q1 b0','X q1','HMR q1 b0'],
                  [('input',[(True,0)])],2,1)
    with pytest.raises(ValueError,match='UNKNOWN_INTERVAL_BUDGET'):
        S.invoice(p,max_intervals=1)
    q=tmp_path/'unbalanced.kmb'
    write_program(q,['PUSH_CONDITION if b0','X q1'],[('input',[(True,0)])],2,1)
    with pytest.raises(ValueError,match='unbalanced'):
        S.invoice(q)


def test_width_cli_retains_full_artifact_and_refuses_overwrite(tmp_path):
    from ssr.tasks import cli
    from argparse import Namespace
    import json
    p=tmp_path/'source.kmb'
    write_program(p,['CX q0 q1','HMR q1 b0','CX q0 q2','HMR q2 b0'],
                  [('input',[(True,0)])],3,1)
    a=Namespace(source=str(p),out=str(tmp_path/'out'),chunk_ops=2,max_intervals=100)
    r=cli.width(a)
    assert r['peak']==2 and r['interval_count']==2
    assert r['is_global_width_lower_bound'] is False
    with np.load(tmp_path/'out/intervals.npz',allow_pickle=False) as z:
        assert z['intervals'].shape==(2,4)
        assert z['peak_runs'].tolist()==[[0,4]]
    assert json.loads((tmp_path/'out/result.json').read_text())==r
    with pytest.raises(FileExistsError):cli.width(a)
