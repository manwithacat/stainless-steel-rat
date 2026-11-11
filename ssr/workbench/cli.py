"""Stainless Steel Rat investigation commands; no search-policy changes."""
import argparse,json,sys
from pathlib import Path
from ssr.workbench.bridge import SSRWorkbench

def compact(value,max_items=12,max_text=600,depth=0):
 if isinstance(value,dict):return {k:compact(v,max_items,max_text,depth+1) for k,v in value.items()}
 if isinstance(value,list):return [compact(v,max_items,max_text,depth+1) for v in value[:max_items]]+([{'more_items':len(value)-max_items}] if len(value)>max_items else [])
 if isinstance(value,str) and len(value)>max_text:return value[:max_text]+'…'
 return value

def main():
 p=argparse.ArgumentParser(prog='python -m ssr.workbench',description=__doc__);p.add_argument('--run',required=True,type=Path,help='existing circuit environment root');p.add_argument('--journal',required=True,type=Path,help='separate investigation evidence root');p.add_argument('--max-queries',type=int);p.add_argument('--max-full-queries',type=int)
 subs=p.add_subparsers(dest='command',required=True);q=subs.add_parser('query');q.add_argument('--request',required=True,help='typed JSON query');q.add_argument('--state',default=None);q.add_argument('--full-output',action='store_true');a=subs.add_parser('apply-query');a.add_argument('--id',required=True);r=subs.add_parser('read-query');r.add_argument('--id',required=True);r.add_argument('--full-output',action='store_true');subs.add_parser('status')
 args=p.parse_args()
 try:
  w=SSRWorkbench(args.run,args.journal,args.max_queries,args.max_full_queries)
  if args.command=='query':result=w.query(json.loads(args.request),args.state)
  elif args.command=='apply-query':result=w.apply_query(args.id)
  elif args.command=='read-query':result=w.read_query(args.id)
  else:result=w.status()
  print(json.dumps(result if getattr(args,'full_output',False) else compact(result),indent=2,allow_nan=False))
 except (ValueError,RuntimeError) as exc:print(json.dumps({'status':'error','error':str(exc)}));sys.exit(2)

if __name__=='__main__':main()
