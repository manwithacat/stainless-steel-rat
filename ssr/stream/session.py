"""Experimental native Rat action loop; separate acceptance model and state store."""
import sys,json
from pathlib import Path
from ssr.stream.stream import StreamingProbe,sha
from ssr.mouse.evaluator import default_contract,digest
from ssr.mouse.store import StateStore
from ssr.mouse import actions
from ssr.mouse.environment import CircuitMouse

class NativeRat:
 # Subclasses swap the evaluator and extend the bound code fingerprints here
 # (previously done by loading private module copies and patching globals).
 probe_class=StreamingProbe
 @classmethod
 def core_fingerprints(cls):return CircuitMouse._fingerprints()
 def __init__(self,root,engine_python,source=None,contract=None,debt_fraction=None):
  self.root=Path(root);cp=self.root/'context.json';old=json.loads(cp.read_text())['context'] if cp.exists() else None
  contract=contract or (old['contract'] if old else default_contract());self.probe=self.probe_class(engine_python,contract)
  source_sha=sha(source) if source else old['source_sha256'] if old else None
  if source_sha is None:raise ValueError('new run requires source')
  debt_fraction=old['debt_fraction'] if debt_fraction is None and old else 0.05 if debt_fraction is None else float(debt_fraction)
  if not 0 <= debt_fraction <= 0.5:raise ValueError('debt_fraction must be between 0 and 0.5')
  context={'schema':'ssr-native-rat/1','source_sha256':source_sha,'contract':contract,'backend':self.probe.identity,'core_fingerprints':self.core_fingerprints(),'controller':{str(Path(__file__)):sha(__file__),str(Path(actions.__file__)):sha(actions.__file__)},'acceptance':'all legal inputs under native chunk-seeded7/101; final scratch/input/tolerance; no cumulative dirty-reset check','loss':'padded native fixed-seed estimate; not official expected cost','settings':{'threads':4,'group_chunks':16,'seeds':[7,101]},'budgets':{'attempts':8,'evaluations':8},'debt_fraction':debt_fraction}
  self.store=StateStore(root,context);self.context=context
  events=self.store.read_events();snap=next((e['payload']['snapshot'] for e in reversed(events) if 'snapshot' in e['payload']),None)
  if snap:self.current=snap['current'];self.incumbent=snap['incumbent'];self.stack=snap['stack']
  else:
   if source is not None:self.store.add_state(source)
   self.current=self.incumbent=source_sha;self.stack=[source_sha]
   r=self._evaluate(source_sha)
   if not r['valid_on_native_models']:raise ValueError('source fails native contract')
   self._event('init',{})
 def _path(self,state):self.store.get_state(state);return self.store.objects/(state+'.kmb')
 def _event(self,kind,payload):self.store.append_event(kind,{**payload,'snapshot':{'current':self.current,'incumbent':self.incumbent,'stack':list(self.stack)}})
 def _count(self,kind):return sum(e['kind']==kind for e in self.store.read_events())
 def _evaluate(self,state):
  cached=self.store.get_evaluation(state,'native-full')
  if cached:self.store.append_event('cache_hit',{'state':state});return cached['receipt']
  if self._count('evaluation_started')>=8:raise ValueError('native evaluation budget exhausted')
  self.store.append_event('evaluation_started',{'state':state})
  r=self.probe.evaluate(self._path(state),threads=4,group_chunks=16)
  self.store.record_evaluation(state,'native-full',r);return r
 def receipt(self,state):return self.store.get_evaluation(state,'native-full')['receipt']
 def observe(self):
  r=self.receipt(self.current)
  return {'agent':'Stainless Steel Rat','backend':'experimental native','state_sha256':self.current,'incumbent_sha256':self.incumbent,'declared_qubits':r['declared_qubits'],'loss_estimate':r['loss_estimate'],'acceptance':self.context['acceptance'],'debt_fraction':self.context['debt_fraction'],'attempts':self._count('attempt_started'),'evaluations':self._count('evaluation_started'),'actions':['recolour','reserve_qubits','advance_hmr','park_recompute','park_factored','park_one_scratch','replace_window'],'single_writer_required':True}
 def propose(self,action):
  self.probe._guard()
  if self._count('attempt_started')>=8:raise ValueError('attempt budget exhausted')
  number=self._count('attempt_started');parent=self.current
  self.store.append_event('attempt_started',{'parent':parent,'action':action})
  try:
   built=actions.apply_action(self._path(parent),action,self.root/'attempts'/str(number));state=self.store.add_state(built['candidate'])['sha256'];r=self._evaluate(state)
   ceiling=self.receipt(self.context['source_sha256'])['loss_estimate']*(1+self.context['debt_fraction'])
   if not r['valid_on_native_models']:result={'status':'rejected','child':state}
   elif r['loss_estimate']>ceiling:result={'status':'pruned','child':state}
   elif state==self.current or state in self.stack:result={'status':'duplicate','child':state}
   else:
    self.current=state;self.stack.append(state)
    if r['loss_estimate']<self.receipt(self.incumbent)['loss_estimate']:self.incumbent=state
    result={'status':'entered_native_model','child':state,'loss_estimate':r['loss_estimate']}
  except (ValueError,AssertionError,actions.ActionError) as e:result={'status':'not_entered','error':str(e)}
  self._event('transition',{'parent':parent,'action':action,'result':result});return result
 def rollback(self):
  if len(self.stack)>1:self.stack.pop();self.current=self.stack[-1]
  self._event('rollback',{});return self.observe()
