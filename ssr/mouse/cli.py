"""Typed JSON interface to the persistent invsqrt circuit mouse."""
import argparse,json,sys
from pathlib import Path
from .environment import CircuitMouse

def main():
 p=argparse.ArgumentParser(prog='python -m ssr.mouse',description=__doc__);p.add_argument('--run',required=True,type=Path)
 sub=p.add_subparsers(dest='command',required=True)
 init=sub.add_parser('init');init.add_argument('--source',required=True,type=Path);init.add_argument('--contract',type=Path);init.add_argument('--mode',choices=['task-contract','source-phase'],default='task-contract');init.add_argument('--max-attempts',type=int,default=8);init.add_argument('--max-full',type=int,default=6);init.add_argument('--max-sampled',type=int,default=16);init.add_argument('--sample-rows',type=int,default=1024);init.add_argument('--debt-fraction',type=float,default=.05)
 sub.add_parser('observe');step=sub.add_parser('step');step.add_argument('--action',required=True,help='JSON typed action');back=sub.add_parser('rollback');back.add_argument('--reason',default='agent requests branch rollback');explore=sub.add_parser('explore');explore.add_argument('--steps',type=int,default=8)
 official=sub.add_parser('record-official');official.add_argument('--report',required=True,type=Path);official.add_argument('--state',default=None)
 args=p.parse_args()
 try:
  if args.command=='init':
   if (args.run/'context.json').exists():raise ValueError('init requires a fresh run; use observe to resume')
   contract=json.loads(args.contract.read_text()) if args.contract else None
   e=CircuitMouse(args.run,args.source,contract,args.mode,args.max_attempts,args.max_full,args.max_sampled,args.sample_rows,args.debt_fraction);result=e.observe()
  else:
   e=CircuitMouse(args.run)
   if args.command=='observe':result=e.observe()
   elif args.command=='step':result=e.propose(json.loads(args.action))
   elif args.command=='rollback':result=e.rollback(args.reason)
   elif args.command=='explore':result=e.explore(args.steps)
   elif args.command=='record-official':result=e.attach_official(args.report,args.state)
  print(json.dumps(result,indent=2,allow_nan=False))
 except (ValueError,RuntimeError) as exc:
  print(json.dumps({'status':'error','error':str(exc)}));sys.exit(2)

if __name__=='__main__':main()
