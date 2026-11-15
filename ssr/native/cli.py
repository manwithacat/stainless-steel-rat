"""Run a separately scoped Rust diagnostic on an authenticated Rat state."""
import argparse,json,sys
from pathlib import Path
from ssr.native.adapter import NativeProbe,default_engine_python
from ssr.core.store import StateStore
from ssr.core.evaluator import sha
import numpy as np

def main():
 p=argparse.ArgumentParser(prog='python -m ssr.native',description=__doc__);p.add_argument('--run',required=True,type=Path);p.add_argument('--state',required=True);p.add_argument('--engine-python',type=Path,default=default_engine_python(),help='directory containing the kickmix_engine package (default: $SSR_ENGINE_PYTHON)');p.add_argument('--out',required=True,type=Path);p.add_argument('--rows',type=int,default=4096);p.add_argument('--seed',type=int,default=7)
 a=p.parse_args()
 if a.engine_python is None:p.error('--engine-python or SSR_ENGINE_PYTHON is required')
 if a.out.exists():raise ValueError('output already exists')
 if not 1<=a.rows<=65536:raise ValueError('rows must be1..65536')
 context=json.loads((a.run/'context.json').read_text())['context'];store=StateStore(a.run,context);store.get_state(a.state)
 rows=np.unique(np.linspace(1,context['contract']['max_x'],min(a.rows,context['contract']['max_x']),dtype=np.uint64))
 probe=NativeProbe(a.engine_python,context['contract']);receipt,_=probe.run(store.objects/(a.state+'.kmb'),rows,a.seed)
 receipt['parent_context_sha256']=store.context_sha256
 a.out.parent.mkdir(parents=True,exist_ok=True)
 with a.out.open('x') as f:json.dump(receipt,f,indent=2)
 print(json.dumps({'state_sha256':a.state,'valid_on_requested_rows':receipt['valid_on_requested_rows'],'rows':len(rows),'receipt':str(a.out),'loss':None,'navigation_mutated':False}))
if __name__=='__main__':main()
