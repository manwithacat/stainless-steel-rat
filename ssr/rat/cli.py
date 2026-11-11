import argparse,json,sys
from pathlib import Path
from ssr.rat.interface import Rat
from ssr.native.adapter import default_engine_python
p=argparse.ArgumentParser(prog='python -m ssr.rat',description='The Stainless Steel Rat: native observe/query/step/rollback loop')
p.add_argument('--run',required=True);p.add_argument('--engine-python',default=default_engine_python(),help='directory containing the kickmix_engine package (default: $SSR_ENGINE_PYTHON)')
s=p.add_subparsers(dest='command',required=True)
i=s.add_parser('init');i.add_argument('--source',required=True);i.add_argument('--contract')
s.add_parser('observe')
for name,field in [('query','request'),('step','action'),('rollback',None)]:
 a=s.add_parser(name);a.add_argument('--expected',required=True)
 if field:a.add_argument('--'+field,required=True)
def main():
 a=p.parse_args()
 if a.engine_python is None:p.error('--engine-python or SSR_ENGINE_PYTHON is required')
 try:
  contract=json.loads(Path(a.contract).read_text()) if getattr(a,'contract',None) else None
  rat=Rat(a.run,a.engine_python,getattr(a,'source',None),contract)
  if a.command=='query':result=rat.query(json.loads(a.request),a.expected)
  elif a.command=='step':result=rat.step(json.loads(a.action),a.expected)
  elif a.command=='rollback':result=rat.back(a.expected)
  else:result=rat.observe()
  print(json.dumps(result,indent=2))
 except (ValueError,KeyError,TypeError) as exc:print(json.dumps({'status':'error','error':str(exc)}));sys.exit(2)
if __name__=='__main__':main()
