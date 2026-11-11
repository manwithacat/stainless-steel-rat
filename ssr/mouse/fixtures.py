"""Authored tiny integration fixture; not held-out optimization evidence."""
from pathlib import Path
import sys
from fractions import Fraction
from decimal import Decimal,localcontext
import kickmix as km
from .evaluator import V,InvSqrtEvaluator

def write_fixture(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 contract={'task':'invsqrt','width':2,'max_x':3,'beta':'1','precision_bits':24,'official_shots_per_x':64,'system_qubits':12}
 spec=V.ProblemSpecInvSqrt(width=2,max_x=3,beta=Fraction(1),precision_bits=24,shots_per_x=64,system_qubits=12)
 import numpy as np
 targets,_=V.reference_values(spec,np.array([1,2,3],dtype=np.uint64));a,b,c=[int(t) for t in targets]
 angle_b=Fraction(b,1<<63);angle_delta=Fraction((c-a-b)%(1<<64),1<<63)
 with localcontext() as ctx:
  ctx.prec=150
  angle_b=format(Decimal(angle_b.numerator)/Decimal(angle_b.denominator),'f')
  angle_delta=format(Decimal(angle_delta.numerator)/Decimal(angle_delta.denominator),'f')
 lines=['APPEND_TO_REGISTER q0 r0','APPEND_TO_REGISTER q1 r0','REGISTER r0 "x"','CX q0 q3',f'Z_POW q1 {angle_b}','CCX q0 q1 q2',f'Z_POW q2 {angle_delta}','CCX q0 q1 q2','CX q0 q3']
 (out/'source.kmx').write_text('\n'.join(lines)+'\n')
 km.Circuit.from_file(str(out/'source.kmx'),format='kmx').to_file(str(out/'source.kmb'),format='kmb')
 # Operation indices exclude the three register declarations.
 return {'source':str(out/'source.kmb'),'contract':contract,'good_park':{'type':'park_recompute','wire':3,'after':0,'before':5,'terms':[['q0']]},'bad_park':{'type':'park_recompute','wire':3,'after':0,'before':5,'terms':[['q1']]}}


def main():
 """Write the authored two-input fixture to a fresh directory and print its paths, contract and example actions."""
 import argparse,json
 p=argparse.ArgumentParser(prog='python -m ssr.mouse.fixtures',description=main.__doc__);p.add_argument('out',type=Path,help='fresh directory (must not exist)')
 a=p.parse_args();f=write_fixture(a.out)
 (a.out/'contract.json').write_text(json.dumps(f['contract'],indent=2)+'\n')
 print(json.dumps({**f,'contract_path':str(a.out/'contract.json')},indent=2))

if __name__=='__main__':main()
