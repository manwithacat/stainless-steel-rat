import sys
from pathlib import Path
import numpy as np
import pytest
from support import need_engine
ENGINE=need_engine()
import kickmix as km
from ssr.native.adapter import NativeProbe,V
from ssr.core.fixtures import write_fixture

def reference(path,rows,seed,width):
 c=km.Circuit.from_file(str(path),format='kmb');sim=km.Simulator(batch_size=256,seed=seed,counting_operations=True)
 reg=km.array([km.q(i) for i in range(width)]);qs=km.array([km.q(i) for i in range(width,c.num_qubits)])
 phases=[];outputs=[];dirty=[]
 padded=np.pad(rows,(0,(-len(rows))%256),mode='edge').reshape(-1,256)
 for batch in padded:
  sim.clear_for_shot();sim.write_across_shots(reg,V.to_bits(batch,width));sim.do(c)
  phases.extend(V.half_turns_to_units(sim.read_shot_phase(i)) for i in range(256))
  outputs.extend(V.from_bits(sim.read_across_shots(reg)));dirty.extend(sim.read_across_shots(qs).any(axis=0))
 st=sim.operation_statistics()
 return {'phase_units':np.array(phases[:len(rows)],dtype=np.uint64),'x_out':np.array(outputs[:len(rows)]),'scratch_dirty':np.array(dirty[:len(rows)])},int(st.num_toffoli_like)

def test_parity_and_negative_controls(tmp_path):
 f=write_fixture(tmp_path/'fixture');p=NativeProbe(ENGINE,f['contract']);rows=np.array([1,2,3]*100,dtype=np.uint64)
 receipt,out=p.run(f['source'],rows);ref,tof=reference(f['source'],rows,7,2)
 assert receipt['valid_on_requested_rows']
 for key in ref:np.testing.assert_array_equal(out[key],ref[key])
 assert receipt['toffolis_including_padding']==tof
 # Different measurement structure: uncompute via HMR and conditional phase repair.
 text=Path(f['source']).with_suffix('.kmx').read_text().replace('CX q0 q3\n','CX q0 q3\n',1)
 text=text.rsplit('CX q0 q3',1)[0]+'HMR q3 b0\nZ q0 if b0\n'
 for name,extra in [('park',''),('phase','Z q0\n'),('dirty','X q3\n')]:
  kmx=tmp_path/(name+'.kmx');kmx.write_text(text+extra);kmb=tmp_path/(name+'.kmb');km.Circuit.from_file(str(kmx),format='kmx').to_file(str(kmb),format='kmb')
  r,o=p.run(kmb,rows);ref,tof=reference(kmb,rows,7,2)
  for key in ref:np.testing.assert_array_equal(o[key],ref[key])
  assert r['toffolis_including_padding']==tof
  assert r['valid_on_requested_rows']==(name=='park')

def test_limits_and_drift(tmp_path):
 f=write_fixture(tmp_path/'fixture');p=NativeProbe(ENGINE,f['contract'])
 for rows in [[],[0],[4],[1.5],list(range(65537))]:
  with pytest.raises(ValueError):p.run(f['source'],rows)
 p.identity[next(iter(p.identity))]='0'*64
 with pytest.raises(ValueError,match='changed'):p.run(f['source'],[1])
