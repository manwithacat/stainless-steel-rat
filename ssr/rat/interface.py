"""Unified native Rat actions and static queries; serialized single-controller API."""
from pathlib import Path
import json
from ssr.rat import admission, liveness
from ssr.stream import session as core
from ssr.workbench import structure
old_sha=core.sha

class Rat(core.NativeRat):
 # Grouped-reference evaluator; context fingerprints also bind this interface and the static-query helper,
 # so behavioural changes here cannot reuse an older run context.
 probe_class=admission.AdmissionProbe
 @classmethod
 def core_fingerprints(cls):return {**super().core_fingerprints(),**{str(Path(m.__file__)):old_sha(m.__file__) for m in (structure,admission,liveness)},str(Path(__file__)):old_sha(__file__)}
 def context_policy(self):
  return {'schema':'ssr-native-rat/2','acceptance':'all legal x; cumulative dirty resets; zero/7/101; parent-bound activating-subspace screen; INCONCLUSIVE rejects; finite outcomes, not a proof','loss':'engine default-salt official shot schedule and equations; no padding','settings':{'threads':3,'group_chunks':16,'bit_sliced_outcomes':['zero',7,101],'target_limit':60}}
 def _evaluate(self,state):
  cached=self.store.get_evaluation(state,'native-full')
  if cached:self.store.append_event('cache_hit',{'state':state});return cached['receipt']
  if self._count('evaluation_started')>=8:raise ValueError('native evaluation budget exhausted')
  self.store.append_event('evaluation_started',{'state':state})
  result=self.probe.evaluate(self._path(state),work=self.root/'exports',threads=3,group_chunks=16)
  self.store.record_evaluation(state,'native-full',result);return result
 def _transition_receipt(self,parent,state,receipt):
  if not receipt['valid_on_native_models']:return receipt
  level='transition-from-'+parent
  cached=self.store.get_evaluation(state,level)
  if cached:transition=cached['receipt']
  else:
   transition=self.probe.transition(self._path(parent),self._path(state),work=self.root/'exports')
   self.store.record_evaluation(state,level,transition)
  self.store.append_event('transition_admission',transition)
  return {**receipt,'valid_on_native_models':transition['valid_on_native_models']}
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  # Static helpers are already among the core fingerprints except this wrapper's structure module.
  self.structure_sha=old_sha(structure.__file__)
 def observe(self):
  return {**super().observe(),'queries':['overview','window','wire','peak','rank_liveness'],
          'evidence_tier':'local admission prescreen; finite outcomes',
          'loss_scope':self.context['loss']}
 def query(self,request,expected):
  self._expected(expected)
  if self._count('investigation_started')>=12:raise ValueError('query budget exhausted')
  state=self.current
  self._event('investigation_started',{'state_sha256':state,'request':request})
  scope='static structure only; not native execution or value proof'
  try:
   if not isinstance(request,dict):raise TypeError('query request must be an object')
   if request.get('type')=='rank_liveness':
    full=liveness.census(self._path(state),self.context['contract'],self.root/'exports',points=request.get('points',64),panel_rows=request.get('panel_rows',4096),cuts=request.get('cuts'))
    directory=self.root/'investigations';directory.mkdir(exist_ok=True)
    artifact=directory/('rank-%04d.json'%self._count('investigation_started'))
    with artifact.open('x') as stream:json.dump(full,stream,indent=2,allow_nan=False)
    examples=[]
    for row in full['cuts'][:6]:
     examples.append({'cut_before_op':row['cut_before_op'],'free_affine_recovery_excluded':row['free_affine_recovery_excluded'],
       'models':[{'outcome':m['outcome'],'live_count':len(m['live_wires']),'linear_rank':m['linear_rank'],'affine_rank':m['affine_rank'],
                  'panel_relations':m['panel_relations'][:2]} for m in row['models']]})
    result={**{k:v for k,v in full.items() if k!='cuts'},'cut_examples':examples,
            'artifact':str(artifact),'artifact_sha256':old_sha(artifact)}
    scope=full['scope']
   else:result=structure.inspect(self._path(state),request)
  except (ValueError,TypeError,KeyError) as exc:
   self._event('investigation_error',{'error':str(exc)});raise
  receipt={'state_sha256':state,'request':request,'structure_sha256':self.structure_sha,'result':result,'scope':scope}
  self._event('investigation',receipt);return receipt
 def _expected(self,expected):
  if expected!=self.current:raise ValueError('stale state: observe and use current SHA')
 def step(self,action,expected):
  self._expected(expected);return self.propose(action)
 def back(self,expected):
  self._expected(expected);return self.rollback()
