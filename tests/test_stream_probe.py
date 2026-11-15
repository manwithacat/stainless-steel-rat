import sys
from pathlib import Path
import pytest
from support import need_engine
ENGINE=need_engine()
from ssr.stream.stream import StreamingProbe
from ssr.core.fixtures import write_fixture
import kickmix as km
def test_group_and_thread_invariance_and_negative(tmp_path):
 f=write_fixture(tmp_path/'f');p=StreamingProbe(ENGINE,f['contract'])
 a=p.evaluate(f['source'],1,1);b=p.evaluate(f['source'],4,16)
 assert a['models']==b['models'] and a['loss_estimate']==b['loss_estimate']
 assert a['valid_on_native_models'] and not a['transition_acceptance']
 assert all(m['covered_legal_rows']==3 for m in a['models'])
 for name,op in [('dirty','X q3'),('phase','Z q0')]:
  src=tmp_path/(name+'.kmx');src.write_text(Path(f['source']).with_suffix('.kmx').read_text()+op+'\n');dst=src.with_suffix('.kmb');km.Circuit.from_file(str(src),format='kmx').to_file(str(dst),format='kmb')
  r=p.evaluate(dst);assert not r['valid_on_native_models'] and r['loss_estimate'] is None
 with pytest.raises(ValueError):p.evaluate(f['source'],group_chunks=0)
