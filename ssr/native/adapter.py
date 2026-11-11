"""Bounded native SSR probe; separate evidence model, never a local-model replacement."""
from pathlib import Path
import sys,time,hashlib,json,importlib
import numpy as np
HERE=Path(__file__).resolve().parent
from ssr.mouse.evaluator import V,validate_contract,sha,VERIFIER
from fractions import Fraction

class NativeProbe:
 def __init__(self,engine_python,contract):
  self.engine_python=Path(engine_python).resolve()
  existing=sys.modules.get('kickmix_engine')
  if existing and Path(existing.__file__).resolve().parent.parent!=self.engine_python:raise ValueError('different engine already imported; use a fresh process')
  sys.path.insert(0,str(self.engine_python));self.ke=importlib.import_module('kickmix_engine')
  if Path(self.ke.__file__).resolve().parent.parent!=self.engine_python:raise ValueError('engine import path mismatch')
  self.contract=validate_contract(contract)
  self.spec=V.ProblemSpecInvSqrt(width=contract['width'],max_x=contract['max_x'],beta=Fraction(contract['beta']),precision_bits=contract['precision_bits'],shots_per_x=contract['official_shots_per_x'],system_qubits=contract['system_qubits'])
  self.files=[Path(self.ke.__file__),Path(self.ke._engine.__file__),Path(__file__),VERIFIER]
  self.identity={str(p):sha(p) for p in self.files}
 def _guard(self):
  if any(sha(p)!=h for p,h in self.identity.items()):raise ValueError('backend or adapter changed during session')
 def run(self,path,rows,seed=7,threads=1):
  self._guard();path=Path(path);source=sha(path)
  rows=np.asarray(rows)
  if rows.ndim!=1 or rows.dtype.kind not in 'iu' or not 1<=len(rows)<=65536 or np.any(rows<1) or np.any(rows>self.contract['max_x']):raise ValueError('rows must be 1..65536 legal integer inputs')
  if type(seed) is not int or not 0<=seed<2**256:raise ValueError('seed must be a 256-bit unsigned integer')
  if type(threads) is not int or not 1<=threads<=4:raise ValueError('threads must be1..4')
  # Validate register contract without importing a full native circuit.
  from ssr.qhdl import kmb as K
  k=K.read(path);regs=k.registers
  # KMB reader exposes register entries as (is_qubit, id).
  regdict=dict(regs)
  if set(regdict)!={'x'} or len(regdict['x'])!=self.contract['width'] or not all(q for q,*_ in regdict['x']):raise ValueError('invsqrt x register mismatch')
  xids=[int(i) for _,i,*_ in regdict['x']]
  if len(set(xids))!=len(xids):raise ValueError('duplicate input wire')
  t=time.perf_counter();prog=self.ke.compile_kmb(path);compile_seconds=time.perf_counter()-t
  padded=np.pad(rows.astype(np.uint64),(0,(-len(rows))%256),mode='edge').reshape(1,-1,256)
  t=time.perf_counter();out=self.ke.run(prog,[seed],padded,xids,threads=threads,counting=True);seconds=time.perf_counter()-t
  phase=out['phase_units'].reshape(-1)[:len(rows)];xr=out['x_out'].reshape(-1)[:len(rows)];dirty=out['scratch_dirty'].reshape(-1)[:len(rows)]
  target,tol=V.reference_values(self.spec,rows.astype(np.uint64));err=(phase-target).view(np.int64)
  # Python integer absolute values avoid signed-min overflow.
  phase_ok=np.array([abs(int(e))<=int(t) for e,t in zip(err,tol)])
  good=phase_ok & (xr==rows) & ~dirty.astype(bool);bad=np.flatnonzero(~good)
  self._guard()
  if sha(path)!=source:raise ValueError('circuit changed during execution')
  receipt={'schema':'ssr-native-probe/1','state_sha256':source,'contract':self.contract,'backend_sha256':self.identity,'kernel':self.ke.kernel_info(),'seed':seed,'threads':threads,'rows_sha256':hashlib.sha256(rows.astype('<u8').tobytes()).hexdigest(),'rows':len(rows),'executed_rows_including_padding':padded.size,'padding':'repeat final input; counts include padding','evidence':'native sampled-input diagnostic; not transition acceptance or official verification','measurement_model':'KickMix ChaCha8; one simulator retained across256-shot batches','phase_model':'128-bit accumulation; final2^-64-turn units','valid_on_requested_rows':bool(good.all()),'first_failure':None if not len(bad) else {'row':int(bad[0]),'x':int(rows[bad[0]]),'phase_ok':bool(phase_ok[bad[0]]),'x_restored':bool(xr[bad[0]]==rows[bad[0]]),'scratch_clean':not bool(dirty[bad[0]])},'toffolis_including_padding':int(out['toffoli_count'].sum()),'kind_counts':out['kind_counts'].tolist(),'z_levels':out['z_levels'].tolist(),'compile_seconds':compile_seconds,'simulation_seconds':seconds,'loss':None,'dirty_reset_check':'unavailable; final scratch only'}
  return receipt,{'phase_units':phase,'x_out':xr,'scratch_dirty':dirty}


def default_engine_python():
 """Directory that contains the separate `kickmix_engine` package, from $SSR_ENGINE_PYTHON (or None)."""
 import os
 value=os.environ.get('SSR_ENGINE_PYTHON')
 return Path(value) if value else None


def default_engine_python():
 """Directory that contains the separate `kickmix_engine` package, from $SSR_ENGINE_PYTHON (or None)."""
 import os
 value=os.environ.get('SSR_ENGINE_PYTHON')
 return Path(value) if value else None
