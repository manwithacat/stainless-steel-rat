import argparse,json,sys
from pathlib import Path
from ssr.rat.interface import Rat
from ssr.native.adapter import default_engine_python
p=argparse.ArgumentParser(prog='python -m ssr.rat',description='The Stainless Steel Rat: native observe/query/step/rollback loop')
p.add_argument('--run',required=True);p.add_argument('--engine-python',default=default_engine_python(),help='directory containing the kickmix_engine package (default: $SSR_ENGINE_PYTHON)')
s=p.add_subparsers(dest='command',required=True)
i=s.add_parser('init');i.add_argument('--source',required=True);i.add_argument('--contract')
for name in ('admit','census'):
 a=s.add_parser(name);a.add_argument('--source',required=True);a.add_argument('--contract');a.add_argument('--out',required=True)
 if name=='admit':
  a.add_argument('--parent');a.add_argument('--transition-only',action='store_true');a.add_argument('--threads',type=int,default=3)
 else:
  a.add_argument('--points',type=int,default=64);a.add_argument('--panel-rows',type=int,default=4096)
s.add_parser('observe')
for name,field in [('query','request'),('step','action'),('rollback',None)]:
 a=s.add_parser(name);a.add_argument('--expected',required=True)
 if field:a.add_argument('--'+field,required=True)
def main():
 a=p.parse_args()
 if a.command!='census' and a.engine_python is None:p.error('--engine-python or SSR_ENGINE_PYTHON is required')
 try:
  contract=json.loads(Path(a.contract).read_text()) if getattr(a,'contract',None) else None
  if a.command in ('admit','census'):
   from ssr.core.evaluator import default_contract
   contract=contract or default_contract()
   if a.command=='census':
    from ssr.rat.liveness import census
    result=census(a.source,contract,Path(a.run)/'exports',points=a.points,panel_rows=a.panel_rows)
   else:
    from ssr.rat.admission import AdmissionProbe
    probe=AdmissionProbe(a.engine_python,contract)
    if a.transition_only and not a.parent:raise ValueError('--transition-only requires --parent')
    transition=probe.transition(a.parent,a.source,work=Path(a.run)/'exports') if a.parent else None
    if a.transition_only or (transition and not transition['valid_on_native_models']):result=transition
    else:
     result=probe.evaluate(a.source,work=Path(a.run)/'exports',threads=a.threads)
     if transition:result['transition']=transition
   with Path(a.out).open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False)
   print(json.dumps({k:v for k,v in result.items() if k not in ('cuts','screen','backend_sha256')},indent=2))
   return 0 if result.get('valid_on_native_models',True) else 1
  rat=Rat(a.run,a.engine_python,getattr(a,'source',None),contract)
  if a.command=='query':result=rat.query(json.loads(a.request),a.expected)
  elif a.command=='step':result=rat.step(json.loads(a.action),a.expected)
  elif a.command=='rollback':result=rat.back(a.expected)
  else:result=rat.observe()
  print(json.dumps(result,indent=2))
  return 0
 except (ValueError,KeyError,TypeError) as exc:print(json.dumps({'status':'error','error':str(exc)}));sys.exit(2)
if __name__=='__main__':sys.exit(main())
