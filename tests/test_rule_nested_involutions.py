"""Positive nested pair and intervening mutation refusal."""
import tempfile
from pathlib import Path

import numpy as np

from ssr.rules.nested_involutions import K,scan


def make(path,mutate):
    ops=[0x31,0x21]
    if mutate:ops.append(0x11)
    ops.extend((0x21,0x31))
    K.write_kmb(path,np.array(ops,dtype=np.uint8),
                {'qqq0':[0,1],'qqq1':[1,0],'qqq2':[2,2],
                 'qq0':[0,0],'qq1':[3,3],
                 'q0':[3] if mutate else []},
                registers=[('s',[(True,0)])],num_qubits=4,num_bits=0)


def test_nested_pair():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'yes.kmb';make(path,False)
        script=Path(tmp)/'edits.qed'
        result=scan(path,script)
        assert result['counts']=={'CX':1,'CCX':1},result
        assert result['charged_pairs']=={'CCX':1}
        assert script.read_text()==''.join(f'delete {i}\n' for i in range(4))


def test_mutation_refusal():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'no.kmb';make(path,True)
        result=scan(path)
        assert result['charged_pairs']=={},result


def test_reset_barrier():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'reset.kmb'
        K.write_kmb(path,np.array([0x31,0x12,0x31],dtype=np.uint8),
                    {'qqq0':[0,0],'qqq1':[1,1],'qqq2':[2,2],
                     'q0':[3]},registers=[('s',[(True,0)])],
                    num_qubits=4,num_bits=0)
        assert scan(path)['charged_pairs']=={}


if __name__=='__main__':
    test_nested_pair();test_mutation_refusal();test_reset_barrier()
    print('nested involution controls PASS')
