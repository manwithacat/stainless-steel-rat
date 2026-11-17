"""Authored controls for missed resets and finite-outcome admission boundaries."""
from pathlib import Path

import numpy as np
import pytest

from support import need_engine
ENGINE = need_engine()
import kickmix as km
from ssr.rat.admission import AdmissionProbe
from ssr.qhdl import alloutcome as AO, bitsim as B
from ssr.core.fixtures import write_fixture
from ssr.rat.interface import Rat


def fixture(tmp_path):
    f = write_fixture(tmp_path / 'fixture')
    f['contract']['official_shots_per_x'] = 256
    return f, AdmissionProbe(ENGINE, f['contract'])


def test_reset_hidden_by_final_clean_scratch(tmp_path):
    f, probe = fixture(tmp_path)
    text = Path(f['source']).with_suffix('.kmx').read_text() + 'X q4\nR q4\n'
    p = tmp_path / 'dirty.kmx'; p.write_text(text)
    child = tmp_path / 'dirty.kmb'; km.Circuit.from_file(str(p)).to_file(str(child),format="kmb")
    report = probe.evaluate(child, work=tmp_path / 'exports')
    assert not report['valid_on_native_models']
    assert report['models'][0]['scratch_clean']
    assert report['models'][0]['dirty_reset_count'] == 3
    assert report['pricing'] is None


def test_unknown_and_skipped_activation_cannot_pass(tmp_path):
    # A measurement-dependent gate deletion requires a targeted schedule.
    p = tmp_path / 'parent.kmx'
    p.write_text('APPEND_TO_REGISTER q0 r0\nREGISTER r0 "x"\nHMR q1 b0\nPUSH_CONDITION if b0\nZ q0\nPOP_CONDITION\n')
    c = tmp_path / 'child.kmx'; c.write_text(p.read_text().replace('Z q0\n', ''))
    op1, _, xq = B.parse_kmx(p); op2, _, _ = B.parse_kmx(c)
    # Zero deliberately misses this branch; no random draws and no targets
    # must be INCONCLUSIVE, rather than an equivalence certificate.
    r = AO.check(op1, op2, xq, nq1=2, nq2=2, rows=np.array([1]), max_targets=0, rand_runs=0)
    assert r['verdict'] == 'INCONCLUSIVE'
    r = AO.check(op1, op2, xq, nq1=2, nq2=2, rows=np.array([1]), max_targets=4, rand_runs=0)
    assert r['verdict'] == 'REJECT'
    assert r['runs'][-1]['targets']['min_activated_rows'] == 1


def test_guarded_reset_is_checked_cumulatively(tmp_path):
    p = tmp_path / 'guard.kmx'
    p.write_text('APPEND_TO_REGISTER q0 r0\nREGISTER r0 "x"\nHMR q1 b0\nPUSH_CONDITION if b0\nX q2\nR q2\nPOP_CONDITION\n')
    ops, _, xq = B.parse_kmx(p)
    # Compare identical programs: equivalence alone cannot catch this reset.
    r = AO.check(ops, ops, xq, nq1=3, nq2=3, rows=np.arange(1, 65), rand_runs=2)
    assert r['verdict'] == 'REJECT'
    assert all(not any(run['scratch_dirty']) for run in r['runs'])
    assert any(any(run['dirty_reset_count']) for run in r['runs'])


def test_engine_cost_schedule_no_padding_and_context(tmp_path):
    f, probe = fixture(tmp_path)
    r = probe.evaluate(f['source'], work=tmp_path / 'exports')
    assert r['valid_on_native_models'] and len(r['models']) == 3
    assert r['pricing']['verified_shots'] == 768
    assert not r['all_measurement_histories']
    assert r['loss_estimate'] == r['pricing']['score']
    run = Rat(tmp_path / 'run', ENGINE, f['source'], f['contract'])
    assert run.context['schema'] == 'ssr-native-rat/2'
    run.context['settings']['threads'] = 2
    # A changed stored acceptance context cannot silently resume.
    cp = tmp_path / 'run' / 'context.json'
    cp.write_text(cp.read_text().replace('ssr-native-rat/2', 'ssr-native-rat/1'))
    with pytest.raises(ValueError, match='context'):
        Rat(tmp_path / 'run', ENGINE)


def test_nonconforming_small_contract_is_explicit(tmp_path):
    f = write_fixture(tmp_path / 'fixture')
    f['contract']['official_shots_per_x'] = 64
    probe = AdmissionProbe(ENGINE, f['contract'])
    with pytest.raises(ValueError, match='divisible by 256'):
        probe.evaluate(f['source'], work=tmp_path / 'exports')


def test_outcome_cache_eviction_is_semantically_invisible():
    valid = B.pack_bits(np.ones(65, bool))
    provider = AO.make_provider('rand', 7, 2, valid)
    expected = provider(0).copy()
    for variable in range(1, 100):
        provider(variable)
    np.testing.assert_array_equal(provider(0), expected)


def test_changed_record_activation_reaches_unchanged_gate(tmp_path):
    p = tmp_path / 'parent.kmx'
    prefix = 'APPEND_TO_REGISTER q0 r0\nREGISTER r0 "x"\nHMR q1 b0\n'
    # The only textual change is the record write. Z itself is aligned.
    p.write_text(prefix + 'BIT_STORE0 b1\nPUSH_CONDITION if b0\nPUSH_CONDITION if b1\nZ q0\nPOP_CONDITION\nPOP_CONDITION\n')
    c = tmp_path / 'child.kmx'; c.write_text(p.read_text().replace('BIT_STORE0 b1','BIT_STORE1 b1'))
    ops1, _, xq = B.parse_kmx(p); ops2, _, _ = B.parse_kmx(c)
    r = AO.check(ops1, ops2, xq, nq1=2, nq2=2, rows=np.array([1]), rand_runs=0)
    assert r['aligned_ops_with_changed_activation'] > 0
    assert r['verdict'] == 'REJECT'


def test_inconclusive_transition_cannot_move_current(tmp_path, monkeypatch):
    f, _ = fixture(tmp_path)
    rat = Rat(tmp_path / 'run', ENGINE, f['source'], f['contract'])
    state = rat.current
    monkeypatch.setattr(rat.probe, 'transition', lambda *a, **k: {
        'parent_sha256': state, 'valid_on_native_models': False,
        'screen': {'verdict': 'INCONCLUSIVE'}})
    result = rat.step(f['good_park'], state)
    assert result['status'] == 'rejected' and rat.current == state


def test_standalone_cli_output_and_exit_code(tmp_path, monkeypatch):
    import json
    import runpy
    import sys
    f, _ = fixture(tmp_path)
    contract = tmp_path / 'contract.json'; contract.write_text(json.dumps(f['contract']))
    out = tmp_path / 'rank.json'
    monkeypatch.setattr(sys, 'argv', ['ssr.rat', '--run', str(tmp_path / 'census'),
        'census', '--source', f['source'], '--contract', str(contract), '--out', str(out), '--points', '1'])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module('ssr.rat', run_name='__main__')
    assert exc.value.code == 0
    assert json.loads(out.read_text())['sampled_boundaries'] == 1
    text = Path(f['source']).with_suffix('.kmx').read_text() + 'Z q0\n'
    kmx = tmp_path / 'bad.kmx'; kmx.write_text(text)
    bad = tmp_path / 'bad.kmb'; km.Circuit.from_file(str(kmx)).to_file(str(bad), format='kmb')
    out = tmp_path / 'bad.json'
    monkeypatch.setattr(sys, 'argv', ['ssr.rat', '--run', str(tmp_path / 'gate'),
        'admit', '--source', str(bad), '--parent', f['source'], '--transition-only',
        '--contract', str(contract), '--out', str(out)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module('ssr.rat', run_name='__main__')
    assert exc.value.code == 1
    assert json.loads(out.read_text())['screen']['verdict'] == 'REJECT'
