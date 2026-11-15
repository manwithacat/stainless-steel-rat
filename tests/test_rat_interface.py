import sys
from pathlib import Path
import pytest
from support import need_engine
ENGINE=need_engine()
from ssr.rat.interface import Rat
from ssr.core.fixtures import write_fixture
def test_queries_stale_rollback(tmp_path):
 f=write_fixture(tmp_path/'fixture');r=Rat(tmp_path/'run',ENGINE,f['source'],f['contract']);state=r.current
 q=r.query({'type':'window','start':0,'end':6},state);assert q['state_sha256']==state
 assert r.step(f['bad_park'],state)['status']=='rejected'
 assert r.step(f['good_park'],state)['status']=='entered_native_model'
 with pytest.raises(ValueError,match='stale'):r.step({'type':'recolour'},state)
 r.step({'type':'recolour'},r.current);best=r.incumbent
 assert r.observe()['declared_qubits']==3
 r.back(r.current);assert r.incumbent==best
 assert Rat(tmp_path/'run',ENGINE).observe()==r.observe()
 for _ in range(11):
  with pytest.raises(ValueError):r.query({'type':'not-a-query'},r.current)
 with pytest.raises(ValueError,match='budget'):r.query({'type':'overview'},r.current)
