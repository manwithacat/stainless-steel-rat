"""Check an initialized GF(64) inverse leaf in the fixed three-record ABI."""
from pathlib import Path

from .source import K, operations, sha


def multiply(x, y):
    value = 0
    while y:
        if y & 1:
            value ^= x
        y >>= 1
        x <<= 1
        if x & 64:
            x ^= 0x43
    return value


def certify(packet, ops):
    """Track quantum truth columns and the independent affine HMR coefficients.

    The source uses six low wires. All remaining wires enter zero. Records
    enter arbitrary, so their first access must overwrite them. Unsupported
    operations raise ValueError and make no statement about equivalence.
    """
    if packet.num_bits != 3 or not 12 <= packet.num_qubits <= 22:
        raise ValueError('expected the bounded 12..22 qubit, three-bit leaf interface')
    source = [sum(((x >> j) & 1) << x for x in range(64)) for j in range(6)]
    q = source + [0] * (packet.num_qubits - 6)
    full = (1 << 64) - 1
    bits = [None] * 3
    phases = [0]  # constant followed by the coefficient of each fresh outcome
    charged = 0
    for at, op in enumerate(ops):
        name, w, bit, condition = (op[k] for k in ('name', 'q', 'b', 'condition'))
        if len(w) != len(set(w)) or any(not 0 <= j < len(q) for j in w):
            raise ValueError(f'invalid quantum operands at {at}')
        if any(j is not None and not 0 <= j < 3 for j in (bit, condition)):
            raise ValueError(f'invalid record operands at {at}')
        enable = 1 if condition is None else bits[condition]
        if enable is None:
            raise ValueError(f'caller record read before overwrite at {at}')
        if name == 'BIT_INVERT':
            if bits[bit] is None:
                raise ValueError(f'caller record inverted before overwrite at {at}')
            bits[bit] ^= enable
        elif name in ('NEG', 'Z', 'CZ', 'CCZ'):
            f = full
            for j in w:
                f &= q[j]
            if name == 'CCZ':
                if enable > 1:
                    raise ValueError(f'unsupported outcome-dependent charge at {at}')
                charged += enable
            while enable:
                low = enable & -enable
                phases[low.bit_length() - 1] ^= f
                enable ^= low
        elif condition is not None:
            raise ValueError(f'unsupported conditional {name} at {at}')
        elif name in ('BIT_STORE0', 'BIT_STORE1'):
            bits[bit] = int(name == 'BIT_STORE1')
        elif name == 'HMR':
            old = q[w[0]]
            q[w[0]] = 0
            frames = {tuple((col >> x) & 1 for col in q) for x in range(64)}
            if len(frames) != 64:
                raise ValueError(f'could not prove a uniform outcome after erasure at {at}')
            bits[bit] = 1 << len(phases)
            phases.append(old)
        elif name == 'R':
            if q[w[0]]:
                raise ValueError(f'unsupported reset of a nonzero truth column at {at}')
        elif name == 'SWAP':
            left, right = w
            q[left], q[right] = q[right], q[left]
        elif name in ('X', 'CX', 'CCX'):
            f = full
            for j in w[:-1]:
                f &= q[j]
            q[w[-1]] ^= f
            charged += int(name == 'CCX')
        else:
            raise ValueError(f'unsupported {name} at {at}')
    if any(phases) or q[:6] != source or any(q[12:]):
        raise ValueError('phase, source preservation or clean-return obligation failed')
    for x in range(64):
        y = sum(((col >> x) & 1) << j for j, col in enumerate(q[6:12]))
        if (x == 0 and y != 0) or (x and multiply(x, y) != 1):
            raise ValueError(f'wrong GF64 inverse at {x}')
    if None in bits:
        raise ValueError('caller record lacks a proved overwrite')
    span = {0}
    for mask in bits:
        span.update([v ^ (mask >> 1) for v in span])
    if len(span) != 8:
        raise ValueError('three returned affine records lack rank three')
    return dict(qubits=packet.num_qubits, charged=charged, measurements=len(phases)-1,
                source_inputs=64, observable_words=8, probability_per_word='1/8')


def inspect(path):
    bound = sha(path)
    k = K.read(str(path))
    try:
        result = certify(k, operations(k))
    finally:
        k.raw._mmap.close()
    if sha(path) != bound:
        raise ValueError('leaf changed during proof')
    return dict(sha256=bound, **result)


def compare(source, candidate):
    old, new = inspect(Path(source)), inspect(Path(candidate))
    return dict(schema='ssr-gf64-inverse-channel/1', source=old, candidate=new,
                saved_Toffolis=old['charged']-new['charged'],
                saved_component_qubits=old['qubits']-new['qubits'],
                contract='q0..5 retained, q6..11 fresh inverse, all other qubits clean. '
                         'b0..2 uniform jointly and independent of the quantum output.',
                register_binding='caller must bind these physical ports and the stated clean inputs',
                task_admission='NOT_RUN')
