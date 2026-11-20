import itertools,pytest
from ssr.tasks.atoms import Forms,Values,Refused


def evaluate(form,assign,nodes):
    values={}
    for node in nodes:
        if node['kind']=='product':v=ev(int(node['left'],16),values)&ev(int(node['right'],16),values)
        else:v=assign[node['id']]
        values[node['id']]=v
    return ev(form,values)


def ev(form,values):
    result=form&1
    for number,value in values.items():
        if form>>number&1:result^=value
    return result


def test_canonical_product_all_affine_forms_and_complements():
    f=Forms();[f.atom('input_q',wire=q) for q in range(3)]
    for a,b in itertools.product(range(16),repeat=2):
        product=f.product(a,b)
        for bits in itertools.product(range(2),repeat=3):
            assign=dict(enumerate(bits,1))
            assert evaluate(product,assign,f.nodes)==(ev(a,assign)&ev(b,assign))
    # Restored forms must give the very same exact atom, not a hash agreement.
    assert f.product(2^4,8)==f.product(8,2^4)


def test_linear_control_restore_reveals_exact_zero_and_dirty_entry_refuses():
    rows=[dict(name=n,q=q,b=None,condition=None) for n,q in
          [('CCX',[0,1,2]),('CX',[3,0]),('CX',[3,0]),('CCX',[0,1,2])]]
    m=Values(4,zero=(2,))
    for row in rows:m.step(row)
    assert m.q[2]==0
    dirty=Values(4)
    for row in rows:dirty.step(row)
    assert dirty.q[2]==dirty.initial[2]!=0
    changed=Values(4,zero=(2,))
    for row in rows[:2]+rows[3:]:changed.step(row)
    assert changed.q[2]!=0


def test_captured_conditions_and_conditional_reset_are_exact():
    m=Values(2)
    m.step(dict(name='PUSH_CONDITION',q=[],b=None,condition=0))
    m.step(dict(name='BIT_STORE0',q=[],b=0,condition=None))
    m.step(dict(name='R',q=[1],b=None,condition=None))
    assert m.q[1]!=0 # captured input condition can be zero
    m.step(dict(name='POP_CONDITION',q=[],b=None,condition=None))
    m.step(dict(name='R',q=[1],b=None,condition=None))
    assert m.q[1]==0
    with pytest.raises(Refused,match='UNBALANCED'):m.step(dict(name='POP_CONDITION',q=[]))
    with pytest.raises(Refused,match='BUDGET'):Values(100,max_atoms=2)
