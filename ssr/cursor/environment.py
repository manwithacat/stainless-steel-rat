"""Persistent circuit state graph with task-aware staged checks and rollback."""
from __future__ import annotations
from copy import deepcopy
import json,math,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;CORE=HERE.parent/'core'
from ssr.core.store import StateStore
from ssr.core.actions import apply_action,ActionError
from ssr.core.evaluator import InvSqrtEvaluator,default_contract,fingerprints,sha,digest,B,K,QHDL

CATALOG=[
 {'type':'recolour','parameters':{},'meaning':'Reuse scratch capacity by certified lifetime renaming; inputs pinned.','semantic_proof':'structural'},
 {'type':'advance_hmr','parameters':{'op':'integer','after':'integer'},'meaning':'Move an existing unconditional HMR earlier across disjoint quantum/classical operations.','semantic_proof':'guarded commutation'},
 {'type':'park_recompute','parameters':{'wire':'integer','after':'integer','before':'integer','terms':'list of at most16 constant/linear/quadratic terms'},'meaning':'Measure scratch during an idle gap, rebuild supplied expression later and repair its phase. Expression correctness must be tested.','semantic_proof':'not established until checked'},
 {'type':'replace_window','parameters':{'start':'integer','end':'integer','ops':'list of at most256 KMX-style ops; exact angle128 or source angle copies'},'meaning':'Bounded construction/splice; can alter approximation in task-contract mode.','semantic_proof':'not established until checked'},
]

class BudgetStop(RuntimeError):pass

class StateCursor:
 def __init__(self,root,source=None,contract=None,mode=None,max_attempts=8,max_full=6,max_sampled=16,sample_rows=1024,debt_fraction=.05,max_wires=None):
  self.root=Path(root).absolute();contextpath=self.root/'context.json'
  if contextpath.exists():
   context=json.loads(contextpath.read_text())['context']
   if context['fingerprints']!=self._fingerprints():raise ValueError('evaluator/action code differs from frozen run context')
   if source is not None and sha(source)!=context['source_sha256']:raise ValueError('resume source differs from context')
   if contract is not None and contract!=context['contract']:raise ValueError('resume contract differs from context')
   if mode is not None and mode!=context['mode']:raise ValueError('resume validation mode differs from context')
  else:
   if source is None:raise ValueError('new run needs source')
   for name,v in [('max_attempts',max_attempts),('max_full',max_full),('max_sampled',max_sampled)]:
    if type(v) is not int or v<1:raise ValueError('positive integer '+name+' required')
   if not isinstance(debt_fraction,(int,float)) or not math.isfinite(debt_fraction) or debt_fraction<0:raise ValueError('invalid debt fraction')
   context={'schema':'qhdl-circuit-mouse/1','source_sha256':sha(source),'contract':contract or default_contract(),'mode':mode or 'task-contract','sample_rows':sample_rows,'max_wires':max_wires or K.read(source).num_qubits,'measurement_models':['zero','7','101'],'pricing_models':['7','101'],'fingerprints':self._fingerprints(),'budgets':{'attempts':max_attempts,'full':max_full,'sampled':max_sampled},'debt_fraction':debt_fraction,'action_catalog':CATALOG}
  self.store=StateStore(self.root,context);self.context=self.store.context
  self.current=self.incumbent=self.official_incumbent=None;self.stack=[];self.visited=set();self.tried={};self.edges={};self.calls={'sampled':0,'full':0};self.cache_hits=0;self.attempts=0;self.source_loss=None
  events=self.store.read_events()
  if events:
   last=next((e['payload']['snapshot'] for e in reversed(events) if 'snapshot' in e['payload']),None)
   if last is None:raise ValueError('missing initial checkpoint; preserve damaged run')
   self._restore(last)
   self.calls={level:sum(e['kind']=='evaluation_started' and e['payload'].get('level')==level for e in events) for level in ['sampled','full']}
   self.attempts=sum(e['kind']=='attempt_started' for e in events)
   for event in events:
    if event['kind']=='attempt_started':self.tried.setdefault(event['payload']['parent'],set()).add(event['payload']['action_id'])
   self.source=self._path(context['source_sha256'])
  else:
   meta=self.store.add_state(source);self.source=Path(meta['path']);self.current=meta['sha256'];self.stack=[self.current]
   self._event('source_pending',{'source_sha256':self.current})
  self.evaluator=InvSqrtEvaluator(context['contract'],self.root/'adapter',self.source,context['mode'],context['sample_rows'],context['max_wires'])
  if self.source_loss is None:
   r=self._test(context['source_sha256'],'full')
   if not r['valid']:self._event('source_rejected',{'receipt':r});raise ValueError('source fails local task contract')
   self.current=self.incumbent=context['source_sha256'];self.stack=[self.current];self.visited={self.current};self.source_loss=r['loss'];self._event('init',{'source_sha256':self.current})
  # Recover the best completed full receipt even if interruption happened
  # between evaluation persistence and transition checkpoint. Navigation stays
  # at its last durable checkpoint; evidence and incumbent do not disappear.
  recovered=None
  for path in self.store.evaluations.glob('*.json'):
   record=json.loads(path.read_text())
   if record.get('level')!='full':continue
   state=record['state_sha256'];receipt=self.store.get_evaluation(state,'full')['receipt']
   if receipt.get('valid') and receipt['loss']<self.receipt(self.incumbent)['loss']:
    self.incumbent=state;recovered=state
  if recovered:self._event('incumbent_recovered',{'incumbent':recovered})
 @staticmethod
 def _fingerprints():
  result=fingerprints()
  for p in [HERE/'environment.py']+[CORE/name for name in ['actions.py','store.py','official.py']]:
   result[str(p)]=sha(p)
  for name in ['edit.py','park_rewrite.py']:
   p=QHDL/name;result[str(p)]=sha(p)
  return result
 def _path(self,digest_):
  self.store.get_state(digest_);return self.store.objects/(digest_+'.kmb')
 def _snapshot(self):
  return {'current':self.current,'incumbent':self.incumbent,'official_incumbent':self.official_incumbent,'stack':self.stack,'visited':sorted(self.visited),'tried':{k:sorted(v) for k,v in self.tried.items()},'edges':self.edges,'calls':self.calls,'cache_hits':self.cache_hits,'attempts':self.attempts,'source_loss':self.source_loss}
 def _restore(self,s):
  for name in ['current','incumbent','official_incumbent','stack','edges','calls','cache_hits','attempts','source_loss']:setattr(self,name,deepcopy(s[name]))
  self.visited=set(s['visited']);self.tried={k:set(v) for k,v in s['tried'].items()}
  for state in set(self.stack)|self.visited|{self.current,self.incumbent}:
   if state is not None:self._path(state)
 def _event(self,kind,payload):return self.store.append_event(kind,{**payload,'snapshot':self._snapshot()})
 def _test(self,state,level):
  cached=self.store.get_evaluation(state,level)
  if cached is not None:self.cache_hits+=1;return deepcopy(cached['receipt'])
  if self.calls[level]>=self.context['budgets'][level]:raise BudgetStop(level+' evaluation budget exhausted')
  self.calls[level]+=1
  self.store.append_event('evaluation_started',{'state_sha256':state,'level':level,'call':self.calls[level]})
  receipt=self.evaluator.evaluate(self._path(state),level)
  self.store.record_evaluation(state,level,receipt)
  self.store.append_event('evaluation',{'state_sha256':state,'level':level,'receipt_status':receipt['status'],'fresh':True,'calls':deepcopy(self.calls)})
  return receipt
 def receipt(self,state=None,level='full'):
  r=self.store.get_evaluation(state or self.current,level);return deepcopy(r['receipt']) if r else None
 def propose(self,action):
  if self.attempts>=self.context['budgets']['attempts']:return {'status':'budget','reason':'attempt budget exhausted'}
  parent=self.current;action=deepcopy(action);aid=digest(action);edgeid=digest({'parent':parent,'action':action});self.attempts+=1;self.tried.setdefault(parent,set()).add(aid)
  self.store.append_event('attempt_started',{'parent':parent,'action':action,'action_id':aid,'edge_id':edgeid,'attempt':self.attempts})
  if edgeid in self.edges and self.edges[edgeid]['status']!='candidate_built':
   old=deepcopy(self.edges[edgeid]);child=old.get('child')
   if child and self.store.get_evaluation(child,'full') is not None:self._test(child,'full')
   self._event('replay',{'edge_id':edgeid,'cached_edge':old});return {**old,'replayed':True}
  edge={'parent':parent,'action':action,'edge_id':edgeid,'child':None,'status':'not_built'}
  try:
   built=apply_action(self._path(parent),action,self.root/'attempts'/f'{self.attempts:06d}-{edgeid[:12]}');meta=self.store.add_state(built['candidate']);child=meta['sha256'];edge.update(child=child,action_evidence=built,status='candidate_built')
   self.edges[edgeid]=deepcopy(edge);self._event('candidate_built',edge)
   sample=self._test(child,'sampled')
   if not sample['valid']:edge.update(status='rejected',reason='sampled test failed')
   else:
    full=self._test(child,'full')
    if not full['valid']:edge.update(status='rejected',reason='full-domain local-model test failed')
    elif full['loss']>self.source_loss*(1+self.context['debt_fraction']):edge.update(status='pruned',reason='source-anchored loss ceiling',loss=full['loss'])
    else:
     edge.update(status='duplicate' if child in self.visited else 'entered',loss=full['loss'])
     if full['loss']<self.receipt(self.incumbent)['loss']:self.incumbent=child
     if child not in self.visited:self.visited.add(child);self.current=child;self.stack.append(child)
  except BudgetStop as exc:edge.update(status='budget',reason=str(exc))
  except (ActionError,ValueError,AssertionError) as exc:edge.update(status='guard_rejected',reason=type(exc).__name__+': '+str(exc))
  self.edges[edgeid]=deepcopy(edge);self._event('transition',edge);return edge
 def rollback(self,reason='requested branch rollback'):
  if len(self.stack)==1:self._event('rollback_root',{'reason':reason});return {'status':'root','current':self.current}
  old=self.stack.pop();self.current=self.stack[-1];self._event('rollback',{'from':old,'to':self.current,'reason':reason});return {'status':'rolled_back','from':old,'current':self.current,'incumbent':self.incumbent}
 def affordances(self,limit=6):
  proposals=[{'type':'recolour'}]
  ops,_,_,_=B.load(self.evaluator.export(self._path(self.current)));lastq={};lastb={};depth=0;depths=[]
  for o in ops:
   depths.append(depth)
   if o.code==B.C_PUSH:depth+=1
   elif o.code==B.C_POP:depth-=1
  candidates=[]
  for i,o in enumerate(ops):
   if o.code==B.C_HMR and o.cond<0 and depths[i]==0:
    after=max(lastq.get(o.q[0],-1),lastb.get(o.bit,-1))
    if after>=0 and after<i-1 and depths[after+1]==0:candidates.append((i-after,{'type':'advance_hmr','op':i,'after':after}))
   for q in o.q:lastq[q]=i
   for b in [o.bit,o.cond]:
    if b>=0:lastb[b]=i
  proposals += [a for _,a in sorted(candidates,key=lambda p:(-p[0],p[1]['op']))[:limit]]
  done=self.tried.get(self.current,set());return [a for a in proposals if digest(a) not in done]
 def explore(self,max_steps=8):
  transitions=[];termination='budget'
  for _ in range(max_steps):
   if self.attempts>=self.context['budgets']['attempts']:break
   actions=self.affordances()
   if not actions:
    if any(e['parent']==self.current and e['status']=='candidate_built' for e in self.edges.values()):termination='incomplete_attempt_needs_retry';break
    if len(self.stack)==1:termination='exhausted_bounded_action_menu';break
    transitions.append(self.rollback('no untried automatically listed actions'));continue
   r=self.propose(actions[0]);transitions.append(r)
   if r['status']=='budget':break
  return {'termination':termination,'scope':'automatically listed recolour/HMR moves only; park/window require supplied proposals; no global dead-end claim','transitions':transitions,'observation':self.observe()}
 def official_receipt(self,state=None):
  receipts=[]
  for path in self.store.evaluations.glob('*.json'):
   record=json.loads(path.read_text())
   if record.get('state_sha256')==(state or self.current) and record.get('level','').startswith('official-recorded/'):
    receipts.append(self.store.get_evaluation(record['state_sha256'],record['level'])['receipt'])
  return min(receipts,key=lambda r:r['loss']) if receipts else None
 def attach_official(self,report_path,state=None):
  from ssr.core.official import recorded_receipt
  state=state or self.current;self._path(state)
  receipt=recorded_receipt(report_path,state,self.context['contract'])
  self.store.record_evaluation(state,'official-recorded/'+sha(report_path),receipt)
  old=self.official_receipt(self.official_incumbent) if self.official_incumbent else None
  if old is None or receipt['loss']<old['loss']:self.official_incumbent=state
  self._event('official_recorded',{'state_sha256':state,'receipt':receipt});return receipt
 def observe(self):
  return {'context_sha256':self.store.context_sha256,'contract':self.context['contract'],'mode':self.context['mode'],'current_sha256':self.current,'incumbent_sha256':self.incumbent,'current_receipt':self.receipt(),'incumbent_receipt':self.receipt(self.incumbent),'official_receipt':self.official_receipt(),'official_incumbent_sha256':self.official_incumbent,'stack':list(self.stack),'source_loss':self.source_loss,'loss_ceiling':self.source_loss*(1+self.context['debt_fraction']),'attempts':self.attempts,'fresh_evaluations':dict(self.calls),'cache_hits':self.cache_hits,'budgets':self.context['budgets'],'incomplete_edges':[e for e in self.edges.values() if e['status']=='candidate_built'],'pending_auto_actions':self.affordances(),'action_catalog':CATALOG}


# Former name (ssr.mouse.CircuitMouse), kept for the 0.x series.
CircuitMouse = StateCursor
