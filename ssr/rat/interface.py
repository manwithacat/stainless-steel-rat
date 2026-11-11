"""Unified native Rat actions and static queries; serialized single-controller API."""
from pathlib import Path
from ssr.rat import stream as new_stream
from ssr.stream import session as core
from ssr.workbench import structure
old_sha=core.sha

class Rat(core.NativeRat):
 # Grouped-reference evaluator; context fingerprints also bind this interface and the static-query helper,
 # so behavioural changes here cannot reuse an older run context.
 probe_class=new_stream.StreamingProbe
 @classmethod
 def core_fingerprints(cls):return {**super().core_fingerprints(),str(Path(__file__)):old_sha(__file__),str(Path(structure.__file__)):old_sha(structure.__file__)}
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  # Static helpers are already among the core fingerprints except this wrapper's structure module.
  self.structure_sha=old_sha(structure.__file__)
 def query(self,request,expected):
  self._expected(expected)
  if self._count('investigation_started')>=12:raise ValueError('query budget exhausted')
  state=self.current
  self._event('investigation_started',{'state_sha256':state,'request':request})
  try:result=structure.inspect(self._path(state),request)
  except (ValueError,TypeError,KeyError) as exc:
   self._event('investigation_error',{'error':str(exc)});raise
  receipt={'state_sha256':state,'request':request,'structure_sha256':self.structure_sha,'result':result,'scope':'static structure only; not native execution or value proof'}
  self._event('investigation',receipt);return receipt
 def _expected(self,expected):
  if expected!=self.current:raise ValueError('stale state: observe and use current SHA')
 def step(self,action,expected):
  self._expected(expected);return self.propose(action)
 def back(self,expected):
  self._expected(expected);return self.rollback()
