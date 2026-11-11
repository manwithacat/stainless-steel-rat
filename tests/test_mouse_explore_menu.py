import sys,tempfile,unittest
from pathlib import Path
from support import need_verifier
need_verifier()
from ssr.mouse.environment import CircuitMouse
from ssr.mouse.fixtures import write_fixture

class MenuExhaustionTests(unittest.TestCase):
 def test_automatic_menu_exhaustion_rolls_back_and_keeps_best(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);f=write_fixture(root/'fixture');e=CircuitMouse(root/'run',f['source'],f['contract'],sample_rows=3,max_attempts=12,max_full=8,max_sampled=12)
   e.propose(f['good_park']);e.propose({'type':'recolour'});best=e.incumbent
   r=e.explore(20)
   self.assertEqual(r['termination'],'exhausted_bounded_action_menu');self.assertEqual(e.incumbent,best)
   self.assertTrue(any(x['status']=='rolled_back' for x in r['transitions']))
   self.assertEqual(len(e.stack),1)

if __name__=='__main__':unittest.main()
