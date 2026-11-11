"""Stainless Steel Rat investigative tools with a separate, immutable journal."""
from __future__ import annotations
from copy import deepcopy
import importlib,json,sys,time,fcntl
from pathlib import Path
HERE=Path(__file__).resolve().parent
from ssr.mouse.environment import CircuitMouse
from ssr.mouse.evaluator import InvSqrtEvaluator,sha,digest,QHDL
from ssr.mouse.store import StateStore

def _module(name):return importlib.import_module('ssr.workbench.'+name)

class QueryBudget(RuntimeError):pass

class SSRWorkbench:
 def __init__(self,mouse_run,evidence_root,max_queries=None,max_full_queries=None):
  self.mouse_run=Path(mouse_run).absolute();self.root=Path(evidence_root).absolute()
  if not (self.mouse_run/'context.json').is_file() or any(not (self.mouse_run/n).is_dir() for n in ['objects','events','evaluations']):raise ValueError('existing circuit run required')
  parent=json.loads((self.mouse_run/'context.json').read_text())['context']
  if parent['fingerprints']!=CircuitMouse._fingerprints():raise ValueError('underlying evaluator differs from run context')
  self.parent=StateStore(self.mouse_run,parent)
  files=[HERE/n for n in ['bridge.py','cli.py','structure.py','values.py','trace.py']]+[QHDL/'cheap_function.py']
  code={str(p):sha(p) for p in files}
  oldpath=self.root/'context.json';old=json.loads(oldpath.read_text())['context'] if oldpath.exists() else None
  if old:
   if max_queries is None:max_queries=old['budgets']['queries']
   if max_full_queries is None:max_full_queries=old['budgets']['full_queries']
  max_queries=32 if max_queries is None else max_queries;max_full_queries=4 if max_full_queries is None else max_full_queries
  if type(max_queries) is not int or max_queries<1 or type(max_full_queries) is not int or max_full_queries<0:raise ValueError('invalid investigation budgets')
  context={'schema':'ssr-investigations/1','parent_context_sha256':self.parent.context_sha256,'tools':code,'budgets':{'queries':max_queries,'full_queries':max_full_queries},'scope':'investigation only; navigation and validation budgets unchanged by queries'}
  self.journal=StateStore(self.root,context)
  source_sha=parent['source_sha256'];self.parent.get_state(source_sha);src=self.journal.add_state(self.parent.objects/(source_sha+'.kmb'))
  self.evaluator=InvSqrtEvaluator(parent['contract'],self.root/'adapter',src['path'],parent['mode'],parent['sample_rows'],parent['max_wires'])
  self.structure=_module('structure');self.values=_module('values');self.trace=_module('trace')
 def navigation(self):
  events=self.parent.read_events();snapshot=next((e['payload']['snapshot'] for e in reversed(events) if 'snapshot' in e['payload']),None)
  if snapshot is None:raise ValueError('source run has no durable navigation checkpoint')
  return deepcopy(snapshot)
 def _state(self,state=None):
  state=state or self.navigation()['current'];self.parent.get_state(state)
  return self.journal.add_state(self.parent.objects/(state+'.kmb'))
 def _counts(self):
  events=self.journal.read_events();return {'queries':sum(e['kind']=='query_started' for e in events),'full_queries':sum(e['kind']=='query_started' and e['payload']['full_domain'] for e in events),'cache_hits':sum(e['kind']=='query_cache_hit' for e in events)}
 def _compare(self,path,request,state):
  if set(request)!={'type','other_sha256'}:raise ValueError('compare requires other_sha256')
  other=self._state(request['other_sha256']);a=self.structure.inspect(path,{'type':'overview'});b=self.structure.inspect(other['path'],{'type':'overview'})
  receipts={}
  for key in [state,other['sha256']]:
   envelope=self.parent.get_evaluation(key,'full');r=envelope['receipt'] if envelope else None
   receipts[key]={'status':r.get('status'),'valid':r.get('valid'),'loss':r.get('loss'),'tier':r.get('tier')} if r else None
  ra,rb=receipts[state],receipts[other['sha256']]
  return {'type':'compare','source_sha256':state,'other_sha256':other['sha256'],'this_structure':a,'other_structure':b,'full_local_receipts':receipts,'loss_delta_this_minus_other':ra['loss']-rb['loss'] if ra and rb and ra['valid'] and rb['valid'] else None,'scope':'two states and existing same-context local metrics; no semantic equivalence or new validation'}
 def query(self,request,state=None):
  # Serialize reservations and cache writes across processes sharing this journal.
  with (self.root/"query.lock").open("a") as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   return self._query(request,state)
 def _query(self,request,state=None):
  # Canonicalize before execution; aliases or changed parameters have new keys.
  request=json.loads(json.dumps(request,allow_nan=False));meta=self._state(state);state=meta['sha256'];key=digest({'context':self.journal.context_sha256,'state':state,'query':request});level='investigation/'+key
  cached=self.journal.get_evaluation(state,level)
  if cached:
   self.journal.append_event('query_cache_hit',{'query_id':key,'state_sha256':state});return {**cached['receipt'],'cache_hit':True,'receipt_path':str(self.journal._evaluation_path(state,level))}
  counts=self._counts();full=type(request) is dict and (request.get('level')=='full' or request.get('validation')=='full');budgets=self.journal.context['budgets']
  if counts['queries']>=budgets['queries'] or full and counts['full_queries']>=budgets['full_queries']:raise QueryBudget('investigation budget exhausted; existing cached queries remain readable')
  self.journal.append_event('query_started',{'query_id':key,'state_sha256':state,'request':request,'full_domain':full});started=time.monotonic()
  receipt={'query_id':key,'state_sha256':state,'query_context_sha256':self.journal.context_sha256,'parent_context_sha256':self.parent.context_sha256,'request':request,'status':'ok','navigation_mutated':False}
  try:
   if type(request) is not dict:raise ValueError('query must be an object')
   kind=request.get('type')
   if kind in ['overview','window','wire','peak']:result=self.structure.inspect(meta['path'],request)
   elif kind in ['value','fit_recompute','check_relation']:result=self.values.investigate(self.evaluator,meta['path'],request)
   elif kind=='trace':result=self.trace.investigate_trace(self.evaluator,meta['path'],request)
   elif kind=='compare':result=self._compare(meta['path'],request,state)
   else:raise ValueError('unknown investigation type')
   receipt['result']=result
  except (ValueError,TypeError,IndexError,KeyError,AssertionError) as exc:receipt.update(status='error',error=type(exc).__name__+': '+str(exc),result=None)
  receipt['seconds']=time.monotonic()-started
  self.journal.record_evaluation(state,level,receipt);self.journal.append_event('query_finished',{'query_id':key,'state_sha256':state,'status':receipt['status'],'seconds':receipt['seconds']})
  return {**receipt,'cache_hit':False,'receipt_path':str(self.journal._evaluation_path(state,level))}
 def read_query(self,key):
  if type(key) is not str or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid query ID')
  for path in self.journal.evaluations.glob('*.json'):
   envelope=json.loads(path.read_text())
   if envelope.get('level')=='investigation/'+key:
    return self.journal.get_evaluation(envelope['state_sha256'],envelope['level'])['receipt']
  raise ValueError('unknown query ID')
 def apply_query(self,key):
  receipt=self.read_query(key);result=receipt.get('result') or {};action=result.get('candidate_action')
  if receipt['status']!='ok' or result.get('status')!='validated' or not action:raise ValueError('query contains no validated-scope candidate action')
  rat=CircuitMouse(self.mouse_run)
  if rat.current!=receipt['state_sha256']:raise ValueError('stale proposal: queried SHA differs from current state; query current state or roll back explicitly')
  transition=rat.propose(action);self.journal.append_event('action_submitted',{'query_id':key,'source_sha256':receipt['state_sha256'],'action':action,'transition':transition})
  return {'query_id':key,'source_sha256':receipt['state_sha256'],'query_validation_scope':result.get('candidate_scope'),'transition':transition,'scope':'existing circuit environment tests whole candidate; relation receipt alone is not acceptance'}
 def status(self):return {'agent':'Stainless Steel Rat','abbreviation':'SSR','parent_context_sha256':self.parent.context_sha256,'query_context_sha256':self.journal.context_sha256,'navigation':self.navigation(),'investigations':self._counts(),'budgets':self.journal.context['budgets'],'tools':['overview','window','wire','peak','value','fit_recompute','check_relation','trace','compare']}
