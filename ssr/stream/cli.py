import argparse,json,sys
from pathlib import Path
from ssr.stream.session import NativeRat
from ssr.native.adapter import default_engine_python
p=argparse.ArgumentParser(prog='python -m ssr.stream');p.add_argument('--run',required=True);p.add_argument('--engine-python',default=default_engine_python(),help='directory containing the kickmix_engine package (default: $SSR_ENGINE_PYTHON)')
s=p.add_subparsers(dest='command',required=True);i=s.add_parser('init');i.add_argument('--source',required=True);i.add_argument('--contract');i.add_argument('--debt-fraction',type=float);s.add_parser('observe');s.add_parser('rollback');a=s.add_parser('step');a.add_argument('--action',required=True)
def main():
 args=p.parse_args()
 if args.engine_python is None:p.error('--engine-python or SSR_ENGINE_PYTHON is required')
 contract=json.loads(Path(args.contract).read_text()) if getattr(args,'contract',None) else None
 r=NativeRat(args.run,args.engine_python,getattr(args,'source',None),contract,getattr(args,'debt_fraction',None))
 result=r.propose(json.loads(args.action)) if args.command=='step' else r.rollback() if args.command=='rollback' else r.observe()
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
