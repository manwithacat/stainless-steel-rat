import json,tempfile,unittest
from pathlib import Path
import sys
from support import need_verifier
need_verifier()
from ssr.mouse.environment import CircuitMouse
from ssr.mouse.fixtures import write_fixture

class EnvironmentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.f=write_fixture(self.root/'fixture')
  self.e=CircuitMouse(self.root/'run',self.f['source'],self.f['contract'],max_attempts=12,max_full=8,max_sampled=12,sample_rows=3)
 def tearDown(self):self.tmp.cleanup()
 def test_bad_then_neutral_then_positive_rollback_and_cache(self):
  source=self.e.current;loss=self.e.receipt()['loss']
  bad=self.e.propose(self.f['bad_park']);self.assertEqual(bad['status'],'rejected');self.assertEqual(self.e.current,source)
  good=self.e.propose(self.f['good_park']);self.assertEqual(good['status'],'entered');park=self.e.current;self.assertEqual(self.e.receipt()['loss'],loss)
  result=self.e.propose({'type':'recolour'});self.assertEqual(result['status'],'entered');best=self.e.current;self.assertEqual(self.e.receipt()['metrics']['declared_qubits'],3)
  self.assertLess(self.e.receipt()['loss'],loss);self.e.rollback();self.assertEqual(self.e.current,park);self.assertEqual(self.e.incumbent,best)
  calls=dict(self.e.calls);replay=self.e.propose({'type':'recolour'});self.assertTrue(replay['replayed']);self.assertEqual(self.e.calls,calls);self.assertEqual(self.e.current,park)
  reopened=CircuitMouse(self.root/'run');self.assertEqual(reopened.current,park);self.assertEqual(reopened.incumbent,best);self.assertEqual(reopened.calls,self.e.calls)
 def test_task_contract_allows_changed_acceptable_phase(self):
  # An exact 128-bit tiny phase change is accepted against tolerance, despite
  # differing from source phase by many64-bit units.
  from ssr.mouse.evaluator import K
  k=K.read(self.f['source']);off,n,_=k.offsets['angles'];a=int.from_bytes(bytes(k.raw[off:off+16]),'little')+(1<<80)
  r=self.e.propose({'type':'replace_window','start':1,'end':2,'ops':[f'Z_POW q1 angle128:{a:032x}']})
  self.assertEqual(r['status'],'entered')
 def test_failed_guard_preserves_incumbent_and_records_event(self):
  source=self.e.current;r=self.e.propose({'type':'advance_hmr','op':0,'after':0});self.assertEqual(r['status'],'guard_rejected');self.assertEqual(self.e.current,source)
  self.assertTrue(any(e['kind']=='transition' for e in self.e.store.read_events()))
 def test_sampled_cache_does_not_satisfy_full_cache(self):
  self.assertIsNone(self.e.store.get_evaluation(self.e.current,'sampled'));self.assertIsNotNone(self.e.store.get_evaluation(self.e.current,'full'))
 def test_exhaustion_scope_and_attempt_budget(self):
  self.e.context['budgets']['attempts']=1
  self.e.propose({'type':'recolour'});r=self.e.propose({'type':'recolour'});self.assertEqual(r['status'],'budget')
 def test_interrupted_check_reservation_survives_resume(self):
  self.e.store.append_event('evaluation_started',{'state_sha256':self.e.current,'level':'full','call':2})
  e=CircuitMouse(self.root/'run');self.assertEqual(e.calls['full'],2)


 def test_initial_interruption_resumes_with_reserved_budget(self):
  from unittest.mock import patch
  from ssr.mouse.evaluator import InvSqrtEvaluator
  with patch.object(InvSqrtEvaluator,'evaluate',side_effect=KeyboardInterrupt):
   with self.assertRaises(KeyboardInterrupt):CircuitMouse(self.root/'crash-source',self.f['source'],self.f['contract'],sample_rows=3)
  e=CircuitMouse(self.root/'crash-source');self.assertEqual(e.calls['full'],2);self.assertTrue(e.receipt()['valid'])
 def test_completed_receipt_survives_missing_transition_checkpoint(self):
  self.e.propose(self.f['good_park'])
  from unittest.mock import patch
  real_test=self.e._test
  def test_then_interrupt(state,level):
   receipt=real_test(state,level)
   if level=='full':raise KeyboardInterrupt()
   return receipt
  with patch.object(self.e,'_test',side_effect=test_then_interrupt):
   with self.assertRaises(KeyboardInterrupt):self.e.propose({'type':'recolour'})
  e=CircuitMouse(self.root/'run');self.assertEqual(e.receipt(e.incumbent)['metrics']['declared_qubits'],3)
  self.assertTrue(e.observe()['incomplete_edges']);calls=dict(e.calls)
  r=e.propose({'type':'recolour'});self.assertEqual(r['status'],'entered');self.assertEqual(e.calls,calls)
 def test_resume_cannot_silently_change_contract_or_mode(self):
  changed=dict(self.f['contract']);changed['precision_bits']=23
  with self.assertRaises(ValueError):CircuitMouse(self.root/'run',contract=changed)
  with self.assertRaises(ValueError):CircuitMouse(self.root/'run',mode='source-phase')


 def test_source_phase_mode_rejects_changed_acceptable_approximation(self):
  from ssr.mouse.evaluator import K
  e=CircuitMouse(self.root/'source-mode',self.f['source'],self.f['contract'],mode='source-phase',sample_rows=3)
  k=K.read(self.f['source']);off,n,_=k.offsets['angles'];a=int.from_bytes(bytes(k.raw[off:off+16]),'little')+(1<<80)
  result=e.propose({'type':'replace_window','start':1,'end':2,'ops':[f'Z_POW q1 angle128:{a:032x}']})
  self.assertEqual(result['status'],'rejected')
 def test_incomplete_export_can_resume_without_overwrite(self):
  from ssr.mouse.evaluator import InvSqrtEvaluator,sha
  work=self.root/'new-export';work.mkdir();p=work/(sha(self.f['source'])+'.kmx');p.write_text('incomplete')
  e=InvSqrtEvaluator(self.f['contract'],work,self.f['source'],sample_rows=3,max_wires=4)
  out=e.export(self.f['source']);self.assertNotEqual(out,p);self.assertEqual(p.read_text(),'incomplete');self.assertEqual(e.export(self.f['source']),out)

if __name__=='__main__':unittest.main()
