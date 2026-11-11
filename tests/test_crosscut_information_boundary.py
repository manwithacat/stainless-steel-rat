import numpy as np

from support import need_kickmix
need_kickmix()
from ssr.crosscut import information_boundary as boundary


def _packed(bits, count):
    q = np.zeros((count, 1), np.uint64)
    for wire, values in bits.items():
        q[wire] = boundary.rule.B.pack_bits(np.asarray(values, bool))
    return q


def test_exact_information_loss_returns_input_witness():
    rows = np.array([1, 2, 3, 4], np.int64)
    before = _packed({0: [0, 0, 1, 1], 1: [0, 0, 1, 1], 2: [0, 1, 0, 1]}, 3)
    assert boundary.information_test(before, rows, 0)["determined"]
    assert boundary.information_test(before, rows, 0, extra_exclude=(1,))["conflicting_keys"] == 2
    after = _packed({0: [0, 0, 1, 1], 2: [0, 1, 0, 1]}, 3)
    result = boundary.information_test(after, rows, 0)
    assert result["determined"] is False
    assert result["conflicting_keys"] == 2
    assert {result["witness"]["x0"], result["witness"]["x1"]} == {1, 3}


def test_state_key_with_more_than_sixty_four_wires():
    rows = np.array([1, 2, 3, 4], np.int64)
    q = _packed({0: [0, 0, 1, 1], 65: [0, 0, 1, 1]}, 70)
    assert boundary.information_test(q, rows, 0)["determined"]
    q[65] = 0
    assert boundary.information_test(q, rows, 0)["conflicting_keys"] == 1
