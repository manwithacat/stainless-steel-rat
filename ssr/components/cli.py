"""Portable, source-bound component proofs and constructive rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import formal, measured, quadratic, frame, phase, phase_scan, view
from .common import K, sha

CAPABILITIES = {
    'reversible': 'Exact arbitrary-dirty-entry values and 128-bit phase; <=512 ops. No HMR/reset/guards.',
    'quadratic': 'Exact dense zero-phase quadratic maps; <=2048 ops/256 wires. Comparison, no synthesis.',
    'measured': 'Exact sufficient aligned-outcome instrument proof; <=512 ops/128 variables. Explicit assumptions.',
    'rewrite': 'Reversible phase folding, conjugation and cancellation; emits a proved component.',
    'phase-scan/phase-construct': 'Source-bound CCX/phase/HMR nomination, transported repayment and exact proof; optional full child.',
    'frame': 'Nominated CCX/HMR retiming across a disjoint unchanged body; optional full child.',
    'task_admission': 'Separate. Native ssr-rat supports invsqrt; component proofs do not run DQI/chemistry task gates.',
}


def fingerprints():
    import numpy as np
    from ssr.qhdl import edit
    return {**{'components/'+p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
            'qhdl/kmb.py': sha(K.__file__), 'qhdl/edit.py': sha(edit.__file__),
            'python': sys.version, 'numpy': np.__version__}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def read_program(path, start=0, stop=None, cap=512):
    path = Path(path)
    digest = sha(path)
    if path.suffix == '.json':
        raw = json.loads(path.read_text())
        lines = raw.get('ops') if isinstance(raw, dict) else raw
        if not isinstance(lines, list) or any(not isinstance(s, str) for s in lines):
            raise ValueError('JSON program must be a list of literal operation strings or {"ops": [...]}')
        n = len(lines)
        end = n if stop is None else stop
        if not 0 <= start <= end <= n or end-start > cap:
            raise ValueError(f'select an explicit window of at most {cap} operations')
        # JSON programs must be complete local programs; inherited guard snapshots
        # cannot be recovered by slicing text and resetting condition depth.
        if start or end != n:
            raise ValueError('JSON input must be a complete bounded program; use KMB for source windows')
        records = [view.parse(s) for s in lines]
        result = dict(records=records, inherited_conditions=[], exit_conditions=[])
    else:
        k = K.read(str(path))
        n = len(k.op_types)
        end = n if stop is None else stop
        if not 0 <= start <= end <= n or end-start > cap:
            raise ValueError(f'select an explicit window of at most {cap} operations')
        # The dense quadratic backend can inspect more than the usual512 ops.
        if end == start:
            if n:
                raise ValueError('an empty window inside a nonempty source is not a component')
            result = dict(records=[], inherited_conditions=[], exit_conditions=[])
        else:
            counts = dict.fromkeys(view.KEYS, 0)
            stack = []
            view.advance(k, 0, start, counts, stack)
            result = view.window(path, start, min(end, start+512))
            if end-start > 512:
                # Preserve real per-op guard depths in every bounded chunk.
                records = list(result['records'])
                for lo in range(start+512, end, 512):
                    records += view.window(path, lo, min(end, lo+512))['records']
                result['records'] = records
                result['exit_conditions'] = view.window(path, end-1, end)['exit_conditions']
    for record in result['records']:
        if any(type(q) is not int or not 0 <= q <= 65535 for q in record['q']):
            raise ValueError('component wire ids must be integers in0..65535')
    if sha(path) != digest:
        raise ValueError('program changed during decoding')
    return {**result, 'path': str(path.resolve()), 'sha256': digest,
            'start': start, 'stop': end, 'source_ops': n}


def check_sources(*programs):
    if any(sha(p['path']) != p['sha256'] for p in programs):
        raise ValueError('source changed during proof')


def interface(*records):
    return sorted({q for rows in records for r in rows for q in r['q']})


def compare(args):
    cap = 2048 if args.backend == 'quadratic' else 512
    source = read_program(args.source, args.start, args.stop, cap)
    child = read_program(args.candidate, cap=cap)
    if args.expected_sha256 and source['sha256'] != args.expected_sha256:
        raise ValueError('source SHA mismatch')
    rows, candidate = source['records'], child['records']
    wires = interface(rows, candidate)
    if args.backend == 'measured':
        if not args.contract:
            raise ValueError('measured comparison requires an explicit --contract')
        contract = json.loads(Path(args.contract).read_text())
        unknown = set(contract)-{'zero_qubits', 'private_records', 'outcomes'}
        if unknown:
            raise ValueError('unknown outcome contract fields: '+', '.join(sorted(unknown)))
        result = measured.compare(rows, candidate, zero_qubits=contract.get('zero_qubits', []),
                                  private_records=contract.get('private_records', []),
                                  outcomes=contract.get('outcomes'),
                                  inherited_conditions=source['inherited_conditions']+child['inherited_conditions'])
    else:
        if args.contract:
            raise ValueError('--contract belongs to the measured backend')
        if args.backend == 'quadratic':
            left, li = quadratic.signature(rows, wires)
            right, ri = quadratic.signature(candidate, wires)
            result = dict(equivalent=left == right, signatures=[left, right], info=[li, ri])
        else:
            if len(wires) > 128:
                raise ValueError('reversible component interface exceeds128 wires')
            left, right = [formal.signature(r, wires) for r in (rows, candidate)]
            result = dict(equivalent=left == right, signatures=[left, right])
    check_sources(source, child)
    return dict(schema='ssr-component-comparison/1', backend=args.backend,
                source={k:v for k,v in source.items() if k != 'records'},
                candidate={k:v for k,v in child.items() if k != 'records'},
                equivalent=result['equivalent'], proof=result,
                costs=dict(source=view.costs(rows), candidate=view.costs(candidate)),
                backend_sha256=fingerprints(), full_task_admission='pending',
                scope='Exact local contract only; declared zero/private facts need caller validation')


def rewrite(args):
    source = read_program(args.source, args.start, args.stop)
    if args.expected_sha256 and source['sha256'] != args.expected_sha256:
        raise ValueError('source SHA mismatch')
    rows = source['records']; wires = interface(rows)
    if len(wires) > 128:
        raise ValueError('reversible component interface exceeds128 wires')
    child = {'phase-fold': formal.fold_phase, 'conjugate': formal.conjugate,
             'cancel': formal.cancel_pairs}[args.rule](rows, wires)
    left, right = [formal.signature(r, wires) for r in (rows, child)]
    if left != right:
        raise ValueError('constructor failed exact reversible comparison')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    view.write_module(out/'child.kmb', child, wires)
    check_sources(source)
    result = dict(schema='ssr-reversible-construction/1', rule=args.rule,
                  source_sha256=source['sha256'], source_range=[source['start'], source['stop']],
                  candidate=str((out/'child.kmb').resolve()), candidate_sha256=sha(out/'child.kmb'),
                  equivalent=True, proof=left, costs=dict(source=view.costs(rows), candidate=view.costs(child)),
                  backend_sha256=fingerprints(), full_task_admission='pending',
                  scope='Proved component only; source register schema and whole task not replaced')
    write(out/'proof.json', result)
    return result


def phase_script(product):
    rows = product['records']
    anchors = [r['op'] for r in rows if r['op'] is not None]
    if anchors != list(range(product['start']+1, product['stop'])):
        raise ValueError('constructor did not preserve every nonproducer source op in order')
    lines = [f"delete {product['start']}"]
    pending = []
    for record in rows:
        if record['op'] is None:
            pending.append(view.text(record))
        elif pending:
            lines.append(f"insert {record['op']} => {'; '.join(pending)}")
            pending = []
    if pending:
        lines.append(f"insert {product['stop']} => {'; '.join(pending)}")
    return '\n'.join(lines)+'\n'


def construct_phase(args):
    source_sha = sha(args.source)
    scan = json.loads(Path(args.scan).read_text())
    if scan.get('source_sha256') != source_sha:
        raise ValueError('scan belongs to different source bytes')
    if not 0 <= args.nominee < len(scan.get('nominees', [])):
        raise ValueError('nominee index outside scan')
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    product = phase.build(args.source, scan['nominees'][args.nominee], out)
    original = read_program(args.source, product['start'], product['stop'])
    candidate = read_program(product['candidate'])
    contract = json.loads(Path(product['contract']).read_text())
    proof = measured.compare(original['records'], candidate['records'], outcomes=contract['outcomes'])
    result = {k:v for k,v in product.items() if k != 'records'}
    result.update(schema='ssr-phase-construction/1', source_sha256=source_sha,
                  candidate_sha256=candidate['sha256'], equivalent=proof['equivalent'], proof=proof,
                  backend_sha256=fingerprints(), full_task_admission='pending')
    if proof['equivalent']:
        script = phase_script(product)
        (out/'patch.qed').write_text(script)
        result.update(edit_script=script, edit_script_sha256=sha(out/'patch.qed'))
        if args.emit_child:
            from .materialize import materialize
            result['materialization'] = materialize(args.source, script, args.emit_child)
    check_sources(original, candidate)
    if sha(args.source) != source_sha:
        raise ValueError('source changed during construction')
    write(out/'proof.json', result)
    return result


def parser():
    p = argparse.ArgumentParser(prog='ssr-components', description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('capabilities', help='show tools, limits and separate task-admission scope')
    for command in ('inspect', 'compare', 'rewrite'):
        c = sub.add_parser(command)
        c.add_argument('--source', required=True); c.add_argument('--start', type=int, default=0)
        c.add_argument('--stop', type=int); c.add_argument('--out', required=True)
        c.add_argument('--expected-sha256')
        if command == 'compare':
            c.add_argument('--candidate', required=True); c.add_argument('--contract')
            c.add_argument('--backend', choices=['reversible', 'quadratic', 'measured'], default='reversible')
        if command == 'rewrite':
            c.add_argument('--rule', choices=['phase-fold', 'conjugate', 'cancel'], required=True)
    c = sub.add_parser('phase-scan'); c.add_argument('--source', required=True)
    c.add_argument('--limit', type=int, default=8); c.add_argument('--out', required=True)
    c = sub.add_parser('phase-construct'); c.add_argument('--source', required=True)
    c.add_argument('--scan', required=True); c.add_argument('--nominee', type=int, required=True)
    c.add_argument('--out', required=True); c.add_argument('--emit-child')
    c = sub.add_parser('frame'); c.add_argument('--source', required=True)
    c.add_argument('--first', type=int, required=True); c.add_argument('--hmr', type=int, required=True)
    c.add_argument('--expected-sha256'); c.add_argument('--out', required=True); c.add_argument('--emit-child')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        bound = fingerprints()
        if args.command == 'capabilities':
            print(json.dumps(CAPABILITIES, indent=2)); return 0
        if args.command not in ('rewrite', 'phase-construct') and Path(args.out).exists():
            raise ValueError('output exists; choose a fresh path')
        if args.command == 'compare':
            result = compare(args); write(args.out, result)
        elif args.command == 'inspect':
            result = read_program(args.source, args.start, args.stop)
            if args.expected_sha256 and result['sha256'] != args.expected_sha256:
                raise ValueError('source SHA mismatch')
            result.update(costs=view.costs(result['records']), tier='static source structure')
            write(args.out, result)
        elif args.command == 'rewrite':
            result = rewrite(args)
        elif args.command == 'phase-scan':
            result = phase_scan.scan(args.source, limit=args.limit); write(args.out, result)
        elif args.command == 'phase-construct':
            result = construct_phase(args)
        else:
            digest = sha(args.source)
            if args.expected_sha256 and digest != args.expected_sha256:
                raise ValueError('source SHA mismatch')
            result = frame.certify(args.source, args.first, args.hmr)
            result.update(source_sha256=digest, backend_sha256=fingerprints(), equivalent=True)
            if args.emit_child:
                from .materialize import materialize
                result['materialization'] = materialize(args.source, result['edit_script'], args.emit_child)
            if sha(args.source) != digest:
                raise ValueError('source changed during frame proof')
            write(args.out, result)
        if bound != fingerprints():
            raise ValueError('component backend changed during execution')
        summary = {k:v for k,v in result.items() if k not in ('records', 'proof', 'backend_sha256', 'endpoint', 'endpoint_source', 'endpoint_child')}
        print(json.dumps(summary, indent=2, allow_nan=False))
        return 0 if result.get('equivalent', True) else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'status': 'NOT_ENTERED', 'error': str(error)})); return 2


if __name__ == '__main__':
    sys.exit(main())
