import sys
from pathlib import Path
import pytest
from support import need_engine
ENGINE=need_engine()
from ssr.stream.session import NativeRat
from ssr.core.fixtures import write_fixture
def test_actions_rollback_resume(tmp_path):
 f=write_fixture(tmp_path/'f');r=NativeRat(tmp_path/'run',ENGINE,f['source'],f['contract'])
 assert r.propose(f['bad_park'])['status']=='rejected'
 assert r.propose(f['good_park'])['status']=='entered_native_model'
 assert r.propose({'type':'recolour'})['status']=='entered_native_model'
 assert r.observe()['declared_qubits']==3
 best=r.incumbent;r.rollback();assert r.incumbent==best
 reopened=NativeRat(tmp_path/'run',ENGINE);assert reopened.observe()==r.observe()
 assert reopened.propose({'type':'recolour'})['status']=='entered_native_model'
 assert reopened.incumbent==best
 with pytest.raises(ValueError,match='context'):NativeRat(tmp_path/'run',ENGINE,contract={**f['contract'],'precision_bits':23})

def test_debt_fraction_is_pinned_and_reserve_keeps_incumbent(tmp_path):
 f=write_fixture(tmp_path/'f')
 r=NativeRat(tmp_path/'run',ENGINE,f['source'],f['contract'],debt_fraction=0.5)
 before=r.incumbent
 result=r.propose({'type':'reserve_qubits','num_qubits':5})
 assert result['status']=='entered_native_model'
 assert r.observe()['declared_qubits']==5
 assert r.incumbent==before
 assert NativeRat(tmp_path/'run',ENGINE).context['debt_fraction']==0.5
 with pytest.raises(ValueError,match='context'):
  NativeRat(tmp_path/'run',ENGINE,debt_fraction=0.05)
