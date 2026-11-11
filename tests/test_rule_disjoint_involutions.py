"""Controls for the exact disjoint-corridor involution screen."""
import tempfile
from pathlib import Path

import numpy as np

from ssr.rules.disjoint_involutions import K, scan


def test_charged_pair_and_operand_touch_barrier():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'case.kmb'
        K.write_kmb(
            path,
            np.array([0x31,0x11,0x31,0x30,0x11,0x30,
                      0x31,0x11,0x31],dtype=np.uint8),
            {'qqq0':[0,1,0,3,0,0],
             'qqq1':[1,0,3,1,1,1],
             'qqq2':[2,2,1,0,2,2],
             'q0':[4,4,0]},
            registers=[('s',[(True,0)])],num_qubits=5,num_bits=0,
        )
        result = scan(path)
        assert result['counts'] == {'CCX':1,'CCZ':1,'X':1}, result
        assert result['first']['CCX']['first'] == 0
        assert result['first']['CCX']['second'] == 2
        assert result['first']['CCZ']['first'] == 3
        assert result['first']['CCZ']['second'] == 5


def test_reset_and_guard_barriers():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'barrier.kmb'
        K.write_kmb(
            path,
            np.array([0x31,0x12,0x31,0xb1,0x31],dtype=np.uint8),
            {'qqq0':[0,0,0,0], 'qqq1':[1,1,1,1],
             'qqq2':[2,2,2,2], 'q0':[3], 'b0':[0]},
            registers=[('s',[(True,0)])],num_qubits=4,num_bits=1,
        )
        result = scan(path)
        assert result['charged_pairs'] == {}
        assert result['decision'].startswith('no charged candidate')


if __name__ == '__main__':
    test_charged_pair_and_operand_touch_barrier()
    test_reset_and_guard_barriers()
    print('disjoint involution controls PASS')
