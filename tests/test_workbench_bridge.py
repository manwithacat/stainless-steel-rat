from pathlib import Path
import hashlib
import pytest
from support import need_verifier
need_verifier()
from ssr.workbench.bridge import SSRWorkbench, QueryBudget, StateCursor
from ssr.core.fixtures import write_fixture

def hashes(root):
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

def setup(tmp_path, **budgets):
 f=write_fixture(tmp_path/'fixture')
 rat=StateCursor(tmp_path/'run',f['source'],f['contract'],max_wires=8)
 return rat,SSRWorkbench(tmp_path/'run',tmp_path/'journal',**budgets)

FIT={'type':'fit_recompute','wire':3,'after':0,'before':5,'basis':[0,1,2],'degree':2,'validation':'full'}

def test_query_apply_and_stale_guard(tmp_path):
 rat,w=setup(tmp_path);before=hashes(tmp_path/'run');initial=rat.current
 for q in [{'type':'overview'},{'type':'window','start':0,'end':6},{'type':'wire','wire':3},{'type':'peak'},{'type':'value','at':1,'wires':[0,3],'level':'full'},{'type':'trace','x':1,'at':[0,1,6],'wires':[0,3],'level':'full','outcome':'7'}]:
  r=w.query(q);assert r['status']=='ok',r
 fit=w.query(FIT);assert fit['result']['status']=='validated',fit
 assert fit['result']['terms']==[['q0']]
 wrong=w.query({**{k:v for k,v in FIT.items() if k!='degree'},'type':'check_relation','terms':[['q1']]} )
 assert wrong['result']['status']=='counterexample'
 assert hashes(tmp_path/'run')==before
 assert w.query(FIT)['cache_hit']
 w.apply_query(fit['query_id']);assert w.navigation()['current']!=initial
 count=len(w.parent.read_events())
 with pytest.raises(ValueError,match='stale'):w.apply_query(fit['query_id'])
 assert len(w.parent.read_events())==count
 rat=StateCursor(tmp_path/'run');rat.propose({'type':'recolour'})
 comparison=w.query({'type':'compare','other_sha256':initial})
 assert comparison['status']=='ok',comparison
 assert comparison['result']['loss_delta_this_minus_other']<0
 assert comparison['result']['this_structure']['declared_qubits']==3

def test_budget_cache_and_context(tmp_path):
 rat,w=setup(tmp_path,max_queries=2,max_full_queries=0)
 q={'type':'overview'};r=w.query(q)
 with pytest.raises(QueryBudget):w.query({'type':'value','at':0,'wires':[0],'level':'full'})
 error=w.query({'type':'invalid'});assert error['status']=='error'
 assert w.query(q)['query_id']==r['query_id']
 with pytest.raises(QueryBudget):w.query({'type':'peak'})
 assert SSRWorkbench(tmp_path/'run',tmp_path/'journal').read_query(r['query_id'])['status']=='ok'
 with pytest.raises(ValueError,match='context'):SSRWorkbench(tmp_path/'run',tmp_path/'journal',max_queries=3)
