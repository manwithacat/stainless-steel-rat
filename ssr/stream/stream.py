"""Bounded-memory native all-input diagnostics; distinct from BitSim acceptance."""
from pathlib import Path
import sys,time,hashlib,math
import numpy as np
HERE=Path(__file__).resolve().parent
from ssr.native.adapter import NativeProbe,V,sha

class StreamingProbe(NativeProbe):
 def __init__(self,engine_python,contract):
  super().__init__(engine_python,contract)
  self.identity[str(Path(__file__))]=sha(__file__)
 def evaluate(self,path,threads=1,group_chunks=16,seeds=(7,101)):
  if type(threads) is not int or not 1<=threads<=4:raise ValueError('threads must be1..4')
  if type(group_chunks) is not int or not 1<=group_chunks<=32:raise ValueError('group_chunks must be1..32')
  if not seeds or len(seeds)>3 or any(type(s) is not int or not 0<=s<2**256 for s in seeds):raise ValueError('invalid seeds')
  self._guard();start=time.perf_counter();state=sha(path);prog=self.ke.compile_kmb(path)
  # Public engine register table; no Python full circuit materialisation.
  regs=prog.registers
  if len(regs)!=1 or regs[0][0]!='x' or len(regs[0][1])!=self.contract['width'] or not all(q for q,_ in regs[0][1]):raise ValueError('invalid x register')
  xids=[int(i) for _,i in regs[0][1]]
  if len(set(xids))!=len(xids):raise ValueError('duplicate x wire')
  compile_seconds=time.perf_counter()-start
  maxx=self.contract['max_x'];chunk_rows=16384;nchunks=(maxx+chunk_rows-1)//chunk_rows
  models=[]
  for seed in seeds:
   phase_hash=hashlib.sha256();min_margin=2**64;worst=0.;worst_x=1;first=None;tof=tcount=rot=0;executed=covered=0
   for lo in range(0,nchunks,group_chunks):
    hi=min(nchunks,lo+group_chunks)
    # All chunks are fixed size, including the tail; groups only control memory/parallelism.
    raw=np.arange(lo*chunk_rows+1,hi*chunk_rows+1,dtype=np.uint64)
    rows=np.minimum(raw,maxx);xs=rows.reshape(hi-lo,64,256)
    derived=[int.from_bytes(hashlib.sha256(seed.to_bytes(32,'little')+i.to_bytes(8,'little')).digest(),'little') for i in range(lo,hi)]
    out=self.ke.run(prog,derived,xs,xids,threads=threads,counting=True)
    target,tol=V.reference_values(self.spec,rows)
    phase=out['phase_units'].reshape(-1);err=(phase-target).view(np.int64);used=np.abs(err).view(np.uint64)
    good=(out['x_out'].reshape(-1)==rows)&~out['scratch_dirty'].reshape(-1).astype(bool)&(used<=tol)
    valid_rows=min(len(rows),maxx-lo*chunk_rows);phase_hash.update(phase[:valid_rows].astype('<u8').tobytes());covered+=valid_rows;executed+=len(rows)
    if not good.all() and first is None:
     j=int(np.flatnonzero(~good)[0]);first={'x':int(rows[j]),'x_restored':bool(out['x_out'].reshape(-1)[j]==rows[j]),'scratch_clean':not bool(out['scratch_dirty'].reshape(-1)[j]),'phase_ok':bool(used[j]<=tol[j])}
    if good.all():min_margin=min(min_margin,int((tol-used).min()))
    ratio=used/tol;j=int(ratio.argmax())
    if ratio[j]>worst:worst=float(ratio[j]);worst_x=int(rows[j])
    tof+=int(out['toffoli_count'].sum());tcount+=int(out['z_levels'][:,3].sum());rot+=int(out['z_levels'][:,4:].sum())
   models.append({'seed':seed,'covered_legal_rows':covered,'executed_rows':executed,'valid':first is None,'first_failure':first,'phase_sha256':phase_hash.hexdigest(),'minimum_margin_units':min_margin if first is None else None,'worst_error_over_tolerance':worst,'worst_x':worst_x,'toffolis':tof,'t_count':tcount,'rotations':rot})
  valid=all(m['valid'] for m in models);loss=None
  if valid:
   margin=min(m['minimum_margin_units'] for m in models);mt=np.mean([m['toffolis']/m['executed_rows'] for m in models]);nt=np.mean([m['t_count']/m['executed_rows'] for m in models]);nr=np.mean([m['rotations']/m['executed_rows'] for m in models]);eps=math.pi*margin/2**64/nr if nr else None
   if nr and eps<=0:valid=False
   else:loss=float(prog.num_qubits*(mt+(nt+nr*V.rotation_t_count(eps) if nr else nt)/V.T_PER_TOFFOLI))
  self._guard()
  if sha(path)!=state:raise ValueError('circuit changed during evaluation')
  return {'schema':'ssr-native-stream/1','state_sha256':state,'contract':self.contract,'backend_sha256':self.identity,'kernel':self.ke.kernel_info(),'valid_on_native_models':valid,'models':models,'declared_qubits':prog.num_qubits,'loss_estimate':loss,'loss_scope':'native fixed-seed formula estimate; counts include repeated final input padding; not official expected cost','coverage':'all legal x per native seed, not all measurement histories','schedule':{'chunk_rows':chunk_rows,'chunk_seed':'SHA256(seed_le32||chunk_index_le8)','group_chunks':group_chunks,'threads':threads,'padding':'repeat final legal input to fixed16384-row chunk'},'dirty_reset_check':'unavailable; final scratch only','transition_acceptance':False,'compile_seconds':compile_seconds,'seconds':time.perf_counter()-start}
