"""Portable installed-tool contracts; no competition data or native simulator."""
import json
from pathlib import Path
import pytest

from ssr.components import cli, view, measured, formal
from ssr.components.common import K, E, sha


def module(path, lines):
    rows = [view.parse(s) for s in lines]
    interface = sorted({q for r in rows for q in r['q']})
    view.write_module(path, rows, interface)
    return path


def json_program(path, lines):
    path.write_text(json.dumps(lines))
    return str(path)


def test_reversible_compare_and_wrong_phase(tmp_path):
    old = json_program(tmp_path/'old.json', ['CCZ q0 q1 q2','SWAP q2 q3','X q4','CCZ q0 q1 q3'])
    new = json_program(tmp_path/'new.json', ['SWAP q2 q3','X q4'])
    out = tmp_path/'proof.json'
    assert cli.main(['compare','--source',old,'--candidate',new,'--out',str(out)]) == 0
    proof = json.loads(out.read_text())
    assert proof['equivalent'] and proof['full_task_admission'] == 'pending'
    bad = json_program(tmp_path/'bad.json', ['SWAP q2 q3'])
    assert cli.main(['compare','--source',old,'--candidate',bad,'--out',str(tmp_path/'bad-proof.json')]) == 1
    assert cli.main(['compare','--source',old,'--candidate',new,'--out',str(out)]) == 2


def test_phase_construct_materialize_and_scalar_proof(tmp_path):
    source = module(tmp_path/'source.kmb', ['CCX q0 q1 q2','Z q2','HMR q2 b0'])
    scan = tmp_path/'scan.json'
    assert cli.main(['phase-scan','--source',str(source),'--out',str(scan)]) == 0
    full_child = tmp_path/'whole.kmb'
    out = tmp_path/'construct'
    assert cli.main(['phase-construct','--source',str(source),'--scan',str(scan),
                     '--nominee','0','--out',str(out),'--emit-child',str(full_child)]) == 0
    result = json.loads((out/'proof.json').read_text())
    assert result['equivalent'] and result['before']['static_toffoli_like'] == 1
    assert result['after']['static_toffoli_like'] == 0
    assert result['materialization']['full_header_register_widths_preserved']
    # Independently serialize the identical script through the older editor.
    expected = tmp_path/'expected.kmb'
    E.edit_file(source, (out/'patch.qed').read_text(), expected)
    assert expected.read_bytes() == full_child.read_bytes()
    child = view.window(full_child, 0, len(K.read(full_child).op_types))['records']
    old = view.window(source, 0, 3)['records']
    mapping = {'source': {'2':'m'}, 'child': {str(i):'m' for i,r in enumerate(child) if r['code'] == K.HMR}}
    assert measured.compare(old, child, outcomes=mapping)['equivalent']
    # A missing final phase repayment is a real counterexample, not UNKNOWN.
    bad = child[:-1]
    badmaps = {'source': {'2':'m'}, 'child': {str(i):'m' for i,r in enumerate(bad) if r['code'] == K.HMR}}
    assert not measured.compare(old, bad, outcomes=badmaps)['equivalent']
    changed = module(tmp_path/'changed.kmb', ['X q0','CCX q0 q1 q2','Z q2','HMR q2 b0'])
    assert cli.main(['phase-construct','--source',str(changed),'--scan',str(scan),
                     '--nominee','0','--out',str(tmp_path/'stale')]) == 2


def test_measured_cli_and_inherited_guard_refusal(tmp_path):
    source = json_program(tmp_path/'a.json', ['CCX q0 q1 q2','HMR q2 b0'])
    child = json_program(tmp_path/'b.json', ['HMR q2 b0','CZ q0 q1 if b0'])
    contract = tmp_path/'contract.json'
    contract.write_text(json.dumps({'outcomes': {'source': {'1':'m'}, 'child': {'0':'m'}}}))
    assert cli.main(['compare','--backend','measured','--source',source,'--candidate',child,
                     '--contract',str(contract),'--out',str(tmp_path/'m.json')]) == 0
    kmb = module(tmp_path/'guarded.kmb', ['PUSH_CONDITION if b0','X q0','POP_CONDITION'])
    trivial = json_program(tmp_path/'trivial.json',['X q0'])
    empty_contract = tmp_path/'none.json'
    empty_contract.write_text(json.dumps({'outcomes': {'source':{},'child':{}}}))
    assert cli.main(['compare','--backend','measured','--source',str(kmb),'--start','1','--stop','2',
        '--candidate',trivial,'--contract',str(empty_contract),'--out',str(tmp_path/'guard-proof.json')]) == 2


def test_frame_disjoint_body_and_conflicts(tmp_path):
    source = module(tmp_path/'framed.kmb', ['CCX q0 q1 q2','X q3','X q0','HMR q2 b0'])
    out = tmp_path/'frame.json';child = tmp_path/'frame-child.kmb'
    assert cli.main(['frame','--source',str(source),'--first','0','--hmr','3',
                     '--out',str(out),'--emit-child',str(child)]) == 0
    proof = json.loads(out.read_text())
    assert proof['equivalent'] and proof['body_ops'] == 2
    assert proof['static_toffoli_delta'] == -1
    old = view.window(source,0,4)['records']
    new = view.window(child,0,len(K.read(child).op_types))['records']
    maps = {'source': {'3':'m'}, 'child': {'0':'m'}}
    assert measured.compare(old,new,outcomes=maps)['equivalent']
    bad = module(tmp_path/'bad-frame.kmb', ['CCX q0 q1 q2','Z q2','HMR q2 b0'])
    assert cli.main(['frame','--source',str(bad),'--first','0','--hmr','2',
                     '--out',str(tmp_path/'bad-frame.json')]) == 2


def test_reversible_rewrite_and_dense_quad_window(tmp_path):
    source = module(tmp_path/'fold.kmb', ['CCZ q0 q1 q2','CCZ q0 q1 q2'])
    out = tmp_path/'folded'
    assert cli.main(['rewrite','--rule','phase-fold','--source',str(source),'--out',str(out)]) == 0
    assert len(K.read(out/'child.kmb').op_types) == 0
    many = module(tmp_path/'many.kmb', ['CX q0 q1']*600)
    empty = module(tmp_path/'empty.kmb', [])
    assert cli.main(['compare','--backend','quadratic','--source',str(many),'--candidate',str(empty),
                     '--out',str(tmp_path/'quad.json')]) == 0
    assert cli.main(['inspect','--source',str(many),'--out',str(tmp_path/'oversize.json')]) == 2


def test_backend_resource_and_sparse_wire_limits():
    with pytest.raises(formal.Barrier):
        formal.signature([view.parse('X q65536')],[65536])
    with pytest.raises(formal.Barrier):
        formal.signature([view.parse('X q0')]*513,[0])


def test_streamed_edit_keeps_exact_angle_tags_and_header(tmp_path):
    from ssr.components.materialize import materialize
    source = module(tmp_path/'metadata.kmb', [
        'INFO_TAG "authored # metadata"',
        'Z_POW q3 angle128:00000000000000000000000000000001',
        'CCX q0 q1 q2', 'Z q2', 'HMR q2 b0',
        'Z_POW q0 angle128:fedcba98765432100123456789abcdef',
        'INFO_TAG "tail"'])
    scan = tmp_path/'scan.json'; out = tmp_path/'constructed'; child = tmp_path/'child.kmb'
    assert cli.main(['phase-scan','--source',str(source),'--out',str(scan)]) == 0
    assert cli.main(['phase-construct','--source',str(source),'--scan',str(scan),
        '--nominee','0','--out',str(out),'--emit-child',str(child)]) == 0
    old, new = K.read(source), K.read(child)
    assert bytes(old.raw[old.offsets['angles'][0]-16:]) == bytes(new.raw[new.offsets['angles'][0]-16:])
    assert old.registers == new.registers
    expected = tmp_path/'expected.kmb'
    E.edit_file(source,(out/'patch.qed').read_text(),expected)
    assert child.read_bytes() == expected.read_bytes()
    with pytest.raises(ValueError, match='angle/tag'):
        materialize(source,'delete 1\n',tmp_path/'forbidden.kmb')


def test_disjoint_frame_checks_late_block_and_outcome_record(tmp_path):
    from ssr.components import frame
    # Cross the streaming block boundary; the late target read must not be lost.
    body = ['X q3']*(frame.BLOCK+1)
    good = module(tmp_path/'long.kmb',['CCX q0 q1 q2',*body,'HMR q2 b0'])
    proof = frame.certify(good,0,len(body)+1)
    assert proof['body_ops'] == len(body)
    bad = module(tmp_path/'late-read.kmb',['CCX q0 q1 q2',*body,'Z q2','HMR q2 b0'])
    with pytest.raises(measured.NotEntered,match='body accesses measured'):
        frame.certify(bad,0,len(body)+2)
    record = module(tmp_path/'record-read.kmb',['CCX q0 q1 q2','X q3 if b0','HMR q2 b0'])
    with pytest.raises(measured.NotEntered,match='body accesses outcome'):
        frame.certify(record,0,2)
