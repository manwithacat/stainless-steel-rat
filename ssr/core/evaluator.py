"""Deterministic invsqrt task adapter with explicitly scoped local-model loss."""
from __future__ import annotations
import hashlib,json,math,sys,time
from fractions import Fraction
from pathlib import Path
import numpy as np
import kickmix as km
from ..qhdl import bitsim as B
from ..qhdl import kmb as K
from ..qhdl import lifetime_allocator as A
from .verifier import V,VERIFIER
HERE=Path(__file__).resolve().parent;QHDL=HERE.parent/'qhdl'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def default_contract():
 return {'task':'invsqrt','width':22,'max_x':3133452,'beta':'1','precision_bits':24,'official_shots_per_x':64,'system_qubits':6540}

def validate_contract(contract):
 required=set(default_contract())
 if type(contract) is not dict or set(contract)!=required or contract['task']!='invsqrt':raise ValueError('only explicit invsqrt contract schema supported')
 for name in ['width','max_x','precision_bits','official_shots_per_x','system_qubits']:
  if type(contract[name]) is not int or contract[name]<=0:raise ValueError('positive integer required: '+name)
 if not 1<=contract['width']<=22 or not 1<=contract['max_x']<=min(3133452,(1<<contract['width'])-1):raise ValueError('contract exceeds implemented local-domain limits')
 if Fraction(contract['beta'])<=0:raise ValueError('positive beta required')
 return dict(contract)

def fingerprints():
 files=[Path(__file__),QHDL/'bitsim.py',QHDL/'kmb.py',QHDL/'lifetime_allocator.py',VERIFIER,Path(km.__file__)]
 result={str(p):sha(p) for p in files}
 result['runtime:numpy_version']=np.__version__;result['runtime:python_version']=sys.version
 return result

class InvSqrtEvaluator:
 def __init__(self,contract,work,source=None,mode='task-contract',sample_rows=1024,max_wires=260):
  self.contract=validate_contract(contract);self.work=Path(work);self.work.mkdir(parents=True,exist_ok=True)
  if mode not in ('task-contract','source-phase'):raise ValueError('unknown validation mode')
  if type(sample_rows) is not int or not 1<=sample_rows<=4096:raise ValueError('sample rows must be1..4096')
  self.mode=mode;self.source=Path(source) if source else None;self.sample_rows=sample_rows;self.max_wires=max_wires
  self.spec=V.ProblemSpecInvSqrt(width=contract['width'],max_x=contract['max_x'],beta=Fraction(contract['beta']),precision_bits=contract['precision_bits'],shots_per_x=contract['official_shots_per_x'],system_qubits=contract['system_qubits'])
  self._references={};self._source_phases={}
 def rows(self,level):
  if level=='full':return np.arange(1,self.contract['max_x']+1,dtype=np.int64)
  if level=='sampled':
   rows=np.linspace(1,self.contract['max_x'],min(self.sample_rows,self.contract['max_x']),dtype=np.int64)
   if len(rows)>=3:rows[1]=2
   return np.unique(rows)
  raise ValueError('unknown validation level')
 def export(self,path):
  path=Path(path);key=sha(path)
  for target in sorted(self.work.glob(key+'*.kmx')):
   meta=target.with_suffix('.export.json')
   if not meta.exists():continue # Preserve incomplete derived export; retry in a fresh file.
   record=json.loads(meta.read_text())
   if record!={'source_sha256':key,'kmx_sha256':sha(target)}:raise ValueError('derived KMX export failed integrity check')
   return target
  index=0
  while True:
   target=self.work/(key+(f'.recovery{index}' if index else '')+'.kmx');meta=target.with_suffix('.export.json')
   if not target.exists() and not meta.exists():break
   index+=1
  km.Circuit.from_file(str(path),format='kmb').to_file(str(target),format='kmx')
  with meta.open('x') as f:json.dump({'source_sha256':key,'kmx_sha256':sha(target)},f)
  return target
 def static(self,path):
  k=K.read(path);circ=km.Circuit.from_file(str(path),format='kmb');V.validate_registers(circ,self.spec)
  if k.num_qubits>self.max_wires:raise ValueError('declared width exceeds environment cap')
  reset,_=A.reset_ops(k);ops,qs,order,_=A.references(k);iv=A.build_intervals(k,ops,qs,order,reset);regs=A.register_qubits(k)
  profile=A.live_profile(iv,len(k.op_types),regs,False)
  return {'declared_qubits':int(k.num_qubits),'register_qubits':len(regs),'operations':len(k.op_types),'live_peak':int(profile.max()) if len(profile) else len(regs),'peak_operations':int((profile==profile.max()).sum()) if len(profile) else 0,'live_area':int(profile.sum()),'unused_declared_wires':sorted(set(range(k.num_qubits))-set(qs.tolist())-set(regs)),'static_toffoli_like':int(np.isin(k.op_types,K.TOFFOLI_LIKE).sum())}
 def _reference(self,level,rows):
  if level not in self._references:self._references[level]=V.reference_values(self.spec,rows.astype(np.uint64))
  return self._references[level]
 def _run(self,path,rows,outcome):
  ops,_,xq,nq=B.load(self.export(path));s=B.BitSim(ops,rows=rows,num_qubits=nq,x_qubits=xq,outcome=outcome,count_toffoli=True)
  classes={i:V.z_pow_class(Fraction(o.text.split()[2])) for i,o in enumerate(ops) if o.code==B.C_ZPOW};counts={'t':0,'rotation':0}
  def count_rotation(i,sim):
   act=sim.act;o=ops[i]
   if o.cond>=0:act=sim._bit(o.cond) if act is None else act&sim._bit(o.cond)
   kind=classes[i]
   if kind in counts:counts[kind]+=sim._count(act)
  s.run(snaps=sorted(classes),on_snap=count_rotation)
  return s,counts
 def evaluate(self,path,level):
  start=time.monotonic();receipt={'valid':False,'status':'not_tested','level':level,'tier':'local-model-all-inputs' if level=='full' else 'sampled-local-model','loss':None,'official_loss':None,'mode':self.mode,'measurement_models':['zero','7','101'],'pricing_models':['7','101'],'all_measurement_histories':False,'angle_units_bits':64}
  try:
   metrics=self.static(path);receipt['metrics']=metrics;rows=self.rows(level);target,tol=self._reference(level,rows);reports=[]
   for outcome in ['zero','7','101']:
    s,counts=self._run(path,rows,outcome);phase=s.phase_units();err=(phase-target).view(np.int64);used=np.abs(err).view(np.uint64);good=used<=tol
    source_equal=None
    if self.mode=='source-phase':
     if self.source is None:raise ValueError('source-phase mode requires source')
     key=(level,outcome)
     if key not in self._source_phases:
      ss,_=self._run(self.source,rows,outcome);self._source_phases[key]=ss.phase_units();del ss
     source_equal=bool(np.array_equal(phase,self._source_phases[key]))
    margin=int((tol-used).min()) if good.all() else None
    valid=s.x_restored() and s.scratch_clean() and s.dirty==0 and bool(good.all()) and source_equal is not False
    ratios=np.divide(used,tol,out=np.zeros(len(rows),dtype=float),where=tol>0)
    reports.append({'outcome':outcome,'valid':valid,'x_restored':s.x_restored(),'scratch_clean':s.scratch_clean(),'dirty_resets':s.dirty,'phase_ok':bool(good.all()),'source_phase_equal':source_equal,'worst_error_over_tolerance':float(ratios.max()),'worst_x':int(rows[int(ratios.argmax())]),'min_margin_units':margin,'mean_toffoli':s.toffoli_rows/s.n,'mean_t':counts['t']/s.n,'mean_rotations':counts['rotation']/s.n})
    del s
    if not valid:break
   receipt.update(rows_checked_per_model=len(rows),models_completed=len(reports),checks=reports,valid=len(reports)==3 and all(r['valid'] for r in reports),status='pass' if len(reports)==3 and all(r['valid'] for r in reports) else 'fail')
   if receipt['valid']:
    margin=min(r['min_margin_units'] for r in reports);priced=reports[1:];toff=sum(r['mean_toffoli'] for r in priced)/len(priced);t=sum(r['mean_t'] for r in priced)/len(priced);rot=sum(r['mean_rotations'] for r in priced)/len(priced)
    eps=math.pi*margin/2**64/rot if rot else None
    if rot and not eps>0:receipt.update(valid=False,status='no_rotation_margin')
    else:
     charge=toff+(t+(rot*V.rotation_t_count(eps) if rot else 0))/V.T_PER_TOFFOLI
     receipt.update(loss=metrics['declared_qubits']*charge,price={'mean_toffoli':toff,'mean_t':t,'mean_rotations':rot,'minimum_margin_units':margin,'rotation_epsilon':eps,'gate_charge':charge},loss_scope='official cost formula applied to fixed local outcome models; not official expected cost')
  except (ValueError,AssertionError,KeyError,IndexError,OverflowError) as exc:receipt.update(status='error',error=type(exc).__name__+': '+str(exc))
  receipt['seconds']=time.monotonic()-start;return receipt
