import numpy as np

from support import need_kickmix
need_kickmix()
from ssr.crosscut import rule


def test_factor_preserves_quadratic_truth_table():
    rows = np.arange(64, dtype=np.int64)
    q = np.stack([rule.B.pack_bits(((rows >> i) & 1).astype(bool)) for i in range(6)])
    valid = rule.B.pack_bits(np.ones(len(rows), bool))
    poly = {"linear": (1 << 1) | (1 << 3), "constant": True, "adj": [0] * 6}
    for left, right in [((1 << 0) | (1 << 2), (1 << 1) | (1 << 4)),
                        ((1 << 2) | (1 << 5), (1 << 3) | (1 << 4))]:
        rule.xor_product(poly, left, right)
    expected = rule.evaluate(poly, q, valid)
    products, linear, constant = rule.factor(poly)
    recovered = {"linear": linear, "constant": constant, "adj": [0] * 6}
    for left, right in products:
        rule.xor_product(recovered, left, right)
    np.testing.assert_array_equal(expected, rule.evaluate(recovered, q, valid))
    assert len(products) <= 3
    one_products, one_linear, one_constant = rule.factor_one_scratch(poly)
    assert 1 <= len(one_products) <= 5
    assert all(left.bit_count() == 1 for left, _ in one_products)
    one_recovered = {"linear": one_linear, "constant": one_constant, "adj": [0] * 6}
    for left, right in one_products:
        rule.xor_product(one_recovered, left, right)
    np.testing.assert_array_equal(expected, rule.evaluate(one_recovered, q, valid))
