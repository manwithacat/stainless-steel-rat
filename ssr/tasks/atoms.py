# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Exact affine atoms for bounded Boolean value proofs (not phase proofs).

The two-dimensional-product normalization follows the algebra documented in
ThemBones' dqi_pp_gvn.py. Full integer forms are dictionary keys here; no
fingerprint collision is allowed to stand in for Boolean equality. Atoms can
be dependent Boolean functions; treating them as independent only loses proofs.
"""
class Refused(ValueError):pass


class Forms:
    def __init__(self,max_atoms=50000):
        if type(max_atoms) is not int or not 1<=max_atoms<=50000:raise Refused('ATOM_BUDGET')
        self.max_atoms=max_atoms;self.nodes=[];self.products={}
    def atom(self,kind,**data):
        if len(self.nodes)>=self.max_atoms:raise Refused('UNKNOWN_ATOM_BUDGET')
        number=len(self.nodes)+1
        self.nodes.append(dict(id=number,kind=kind,**data))
        return 1<<number
    def product(self,a,b):
        ac=a&1;bc=b&1;A=a^ac;B=b^bc
        if not A:return b if ac else 0
        if not B:return a if bc else 0
        if A==B:return (A if 1^ac^bc else 0)^(ac&bc)
        u,v=sorted((A,B,A^B))[:2]
        key=(u,v)
        if key not in self.products:self.products[key]=self.atom('product',left=hex(u),right=hex(v))
        linear=0 if set(key)=={A,B} else A if A in key else B
        return self.products[key]^linear^(A if bc else 0)^(B if ac else 0)^(ac&bc)


class Values:
    def __init__(self,nq,zero=(),max_atoms=50000):
        if type(nq) is not int or not 0<=nq<=4096:raise Refused('QUANTUM_BUDGET')
        if any(type(q) is not int or not 0<=q<nq for q in zero):raise Refused('ZERO_INTERFACE')
        self.f=Forms(max_atoms);self.q=[0 if q in zero else self.f.atom('input_q',wire=q) for q in range(nq)]
        self.b={};self.stack=[1];self.initial=self.q.copy()
    def bit(self,b):
        if type(b) is not int or b<0:raise Refused('CLASSICAL_ID')
        if b not in self.b:self.b[b]=self.f.atom('input_b',bit=b)
        return self.b[b]
    def step(self,r):
        name=r['name'];qs=r['q'];bit=r.get('b');cond=r.get('condition')
        if name=='PUSH_CONDITION':
            self.stack.append(self.f.product(self.stack[-1],self.bit(cond)));return
        if name=='POP_CONDITION':
            if len(self.stack)==1:raise Refused('UNBALANCED_CONDITION')
            self.stack.pop();return
        guard=self.stack[-1]
        if cond is not None:guard=self.f.product(guard,self.bit(cond))
        def toggle(q,x):self.q[q]^=self.f.product(guard,x)
        if name in ['NEG','Z','CZ','CCZ','Z_POW','INFO_TAG']:return
        if name=='X':toggle(qs[0],1)
        elif name=='CX':toggle(qs[1],self.q[qs[0]])
        elif name=='CCX':toggle(qs[2],self.f.product(self.q[qs[0]],self.q[qs[1]]))
        elif name in ['SWAP','CSWAP']:
            a,b=qs[-2:];term=self.q[a]^self.q[b]
            if name=='CSWAP':term=self.f.product(term,self.q[qs[0]])
            value=self.f.product(guard,term);self.q[a]^=value;self.q[b]^=value
        elif name in ['R','HMR']:
            q=qs[0]
            if name=='HMR':
                old=self.bit(bit);root=self.f.atom('measurement_root',bit=bit)
                self.b[bit]=old^self.f.product(guard,old^root)
            self.q[q]=self.f.product(self.q[q],guard^1)
        elif name in ['BIT_STORE0','BIT_STORE1']:
            old=self.bit(bit);self.b[bit]=old^self.f.product(guard,old^(name=='BIT_STORE1'))
        elif name=='BIT_INVERT':self.b[bit]=self.bit(bit)^guard
        else:raise Refused('UNSUPPORTED_VALUE_OPERATION:'+name)
