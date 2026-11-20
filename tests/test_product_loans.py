import pytest
from ssr.tasks import park as P
from test_task_entry import write_program


def run(tmp_path,lines,nq=5,pinned=(0,1),peaks=((1,4),)):
    p=tmp_path/'source.kmb'
    write_program(p,lines,[('input',[(True,q) for q in pinned])],nq,1)
    return P.census(p,peaks)


def test_zero_product_copy_inversion_and_write_version(tmp_path):
    r=run(tmp_path,['CCX q0 q1 q2','CX q2 q3','X q3','Z q4','Z q3','Z q2'])
    h=[h for h in r['handles'] if h['wire']==3]
    assert len(h)==1 and h[0]['controls']==[0,1] and h[0]['constant']==1
    assert h[0]['start']==3 and h[0]['stop']==4
    assert r['task_admission']=='NOT_RUN'
    # A changed control kills the syntactic formula, even if restored later.
    r=run(tmp_path,['CCX q0 q1 q2','X q0','X q0','Z q4','Z q2'])
    assert not r['handles']


def test_dirty_target_guard_and_alias_refuse(tmp_path):
    r=run(tmp_path,['CCX q0 q1 q2','Z q3','Z q4','Z q2'],pinned=(0,1,2))
    assert not r['handles']
    r=run(tmp_path,['CCX q0 q1 q2 if b0','Z q3','Z q4','Z q2'])
    assert not r['handles']
    r=run(tmp_path,['PUSH_CONDITION if b0','CCX q0 q1 q2','POP_CONDITION','Z q3','Z q2'])
    assert not r['handles']
    with pytest.raises(ValueError,match='aliased|repeated qubit'):
        run(tmp_path,['CCX q0 q1 q1'])


def test_uncompute_cancels_and_reuse_does_not_inherit_formula(tmp_path):
    r=run(tmp_path,['CCX q0 q1 q2','CCX q1 q0 q2','CX q0 q2','Z q4','Z q2'])
    assert not r['handles']


def test_each_loan_identity_preserves_amplitudes_for_both_outcomes():
    # HMR contributes (-1)^(m*w); the proposed Clifford repayment must cancel
    # it, including the complement's constant, before CCX (+optional X) rebuild.
    import itertools
    for a,b,inverted,m in itertools.product(range(2),repeat=4):
        old=(a&b)^inverted
        phase_hmr=m*old
        phase_repay=m*(a&b)^m*inverted
        assert (phase_hmr^phase_repay)==0
        rebuilt=(a&b)^inverted
        assert rebuilt==old
