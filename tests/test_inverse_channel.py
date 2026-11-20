from types import SimpleNamespace

import pytest
from ssr.tasks.inverse_channel import certify


def op(name, w=(), bit=None, cond=None):
    return dict(name=name, q=w, b=bit, condition=cond)


@pytest.mark.parametrize('ops,message', [
    ([op('HMR', (0,), 0)], 'uniform outcome after erasure'),
    ([op('CX', (0, 6)), op('HMR', (0,), 0)], 'source preservation'),
    ([op('NEG', cond=0)], 'read before overwrite'),
    ([op('HMR', (12,), 0), op('X', (1,), cond=0)], 'unsupported conditional'),
    ([op('CCX', (1, 2, 1))], 'invalid quantum operands'),
    ([op('R', (3,))], 'nonzero truth column'),
])
def test_instrument_refusals(ops, message):
    with pytest.raises(ValueError, match=message):
        certify(SimpleNamespace(num_qubits=18, num_bits=3), ops)
