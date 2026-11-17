from support import need_verifier
need_verifier()
import kickmix as km
from ssr.rat.liveness import ranks, census


def test_affine_constant_and_dependency_witness():
    # q1 = q0 XOR 1: raw linear rank is two, affine dimension is one.
    r = ranks([0b1010, 0b0101], [0, 1], 4, protected=[0])
    assert r['linear_rank'] == 2 and r['affine_rank'] == 1
    assert not r['full_affine_rank']
    assert r['panel_relations'][0]['constant'] == 1
    assert r['panel_relations'][0]['xor_wires'] == [0]
    r = ranks([0b1010, 0b1100], [0, 1], 4)
    assert r['full_affine_rank']


def test_live_xor_positive_and_independent_peak(tmp_path):
    src = tmp_path / 'source.kmx'
    src.write_text('APPEND_TO_REGISTER q0 r0\nAPPEND_TO_REGISTER q1 r0\nAPPEND_TO_REGISTER q2 r0\nREGISTER r0 "x"\nCX q0 q3\nCX q1 q3\nCCX q0 q1 q4\nZ q3\nZ q4\nCCX q0 q1 q4\nCX q1 q3\nCX q0 q3\n')
    kmb = tmp_path / 'source.kmb'; km.Circuit.from_file(str(src)).to_file(str(kmb),format="kmb")
    contract = dict(task='invsqrt', width=3, max_x=7, beta='1', precision_bits=24,
                    official_shots_per_x=256, system_qubits=12)
    r = census(kmb, contract, tmp_path / 'exports', cuts=[3], panel_rows=7)
    m = r['cuts'][0]['models'][0]
    assert m['linear_rank'] == 4 and m['affine_rank'] == 4
    assert m['live_wires'] == [0, 1, 2, 3, 4]
    assert not r['cuts'][0]['free_affine_recovery_excluded']
    assert any(w['wire'] == 3 and w['xor_wires'] == [0, 1] for w in m['panel_relations'])
    # Omit the redundant copy from this interface: x0,x1,x2,x0*x1
    assert ranks([0b1010101, 0b1100110, 0b1111000, 0b1000100], [0, 1, 2, 4], 7)['full_affine_rank']
