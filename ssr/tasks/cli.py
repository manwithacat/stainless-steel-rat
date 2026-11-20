# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Portable task context, source-bound rule census and candidate construction."""
from pathlib import Path
import json
from . import chemistry, supplied
from .source import K, sha, canonical, fingerprint, operations, profile, word_table

COMMANDS = {'tools', 'context', 'scan', 'construct', 'width', 'loans', 'chemistry-relations'}
TASKS = ['invsqrt', 'dqi', 'chemistry']


def add_commands(sub):
    c = sub.add_parser('tools', help='discover task tools and their proof/admission boundaries')
    c.add_argument('--task', choices=TASKS)
    c = sub.add_parser('context', help='inspect a source/family and state task-specific requirements')
    c.add_argument('--task', required=True, choices=TASKS)
    c.add_argument('--source', required=True)
    c.add_argument('--words', help='assembled angle_words NPZ; defaults to family submission.npz')
    c.add_argument('--out', required=True)
    c = sub.add_parser('scan', help='source-bound safe-rule census; never admits a task')
    c.add_argument('--task', required=True, choices=TASKS)
    c.add_argument('--source', required=True)
    c.add_argument('--words')
    c.add_argument('--slot', type=int)
    c.add_argument('--rule', choices=['auto', 'quick', 'supplied'], default='auto')
    c.add_argument('--out', required=True, help='fresh output directory')
    c.add_argument('--max-events', type=int, default=64)
    c = sub.add_parser('chemistry-relations', help='exact typed delta-word constraints; no fitting/task admission')
    c.add_argument('--words', required=True, help='NPZ with assembled angle_words')
    c.add_argument('--relations', required=True, help='int/F/B/G target dialects')
    c.add_argument('--word-bits', type=int, default=7)
    c.add_argument('--out', required=True, help='fresh output directory')
    c = sub.add_parser('loans', help='exact single-product idle loans across named peaks; no joint rewrite')
    c.add_argument('--source', required=True)
    c.add_argument('--width-invoice', required=True, help='result.json from width on identical source')
    c.add_argument('--out', required=True, help='fresh output directory')
    c.add_argument('--max-handles', type=int, default=100000)
    c = sub.add_parser('width', help='bounded-memory peak invoice; no semantic retirement proof')
    c.add_argument('--source', required=True)
    c.add_argument('--out', required=True, help='fresh output directory')
    c.add_argument('--chunk-ops', type=int, default=65536)
    c.add_argument('--max-intervals', type=int, default=2000000)
    c = sub.add_parser('construct', help='reprove a handle, emit a deterministic edit and optional child')
    c.add_argument('--source', required=True)
    c.add_argument('--handle', required=True)
    c.add_argument('--words')
    c.add_argument('--out', required=True, help='fresh output directory')
    c.add_argument('--emit-child')


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def seal(value):
    import hashlib
    return hashlib.sha256(canonical({k:v for k,v in value.items() if k != 'id'})).hexdigest()


def tools(task=None):
    common = [
        dict(command='ssr-rat context --task TASK --source SOURCE --out CONTEXT.json',
             purpose='source hashes, widths, task objective, dependencies and next commands',
             stage='context', requires='NumPy'),
        dict(command='ssr-rat width --source SOURCE --out FRESH',
             purpose='all binding peaks and scratch lifetimes in a conservative reset model',
             stage='structural census', evidence='not a zero-retirement proof or global width lower bound'),
        dict(command='ssr-rat loans --source SOURCE --width-invoice WIDTH/result.json --out FRESH',
             purpose='identify exact product loans and their phase repayment at binding peaks',
             stage='census only', evidence='individually sound handles; no joint schedule, materialization or task proof'),
        dict(command='ssr-rat scan --task TASK --source SOURCE --rule quick --out FRESH',
             purpose='initialized-zero and exact disjoint-involution rules', stage='census',
             evidence='conservative semantic certificates; task gate separate'),
        dict(command='ssr-rat construct --source SOURCE --handle HANDLE.json --out FRESH --emit-child CHILD.kmb',
             purpose='reprove handle and construct source-bound candidate', stage='construction',
             evidence='rule theorem under stated interface; task gate separate'),
    ]
    extra = []
    if task in [None, 'chemistry']:
        extra.append(dict(command='ssr-rat chemistry-relations --words TABLE.npz --relations RELATIONS.txt --word-bits 7 --out FRESH',
                          purpose='check exact coded delta constraints with int/F/B/G targets',stage='structural proof',
                          evidence='not numerical validity, a rounding feasibility proof, or compiled cost'))
        extra.append(dict(command='ssr-rat scan --task chemistry --source FAMILY --words ASSEMBLED.npz --rule supplied --out FRESH',
                          purpose='current CCX-to-CX/X identities on both adjacent word endpoints',
                          stage='constructive census', requires='explicit assembled angle_words',
                          evidence='exact endpoint support and all preceding outcome histories; not arbitrary-word oracle'))
    return dict(schema='ssr-task-tools/1', task=task, portable=common+extra,
                native_invsqrt='ssr-rat --run RUN admit --source CHILD --parent PARENT --out RECEIPT (configure external engine/verifier)',
                dqi_chemistry_task_admission='external gate required; component or census result never admits a task',
                no_improvement='A complete local menu closes only its stated rule/context; use a different mechanism or interface.')


def source_files(source, task):
    p = Path(source)
    if p.is_file():
        return [(None, p)]
    if task != 'chemistry' or not p.is_dir():
        raise ValueError('source must be a KMB, or a chemistry family directory')
    files = []
    for f in p.glob('angle_k_*.kmb'):
        try:
            slot = int(f.stem.removeprefix('angle_k_'))
        except ValueError:
            continue
        files.append((slot, f))
    files.sort()
    if not files or [s for s,_ in files] != list(range(len(files))):
        raise ValueError('chemistry family must have contiguous angle_k_0..K-1.kmb files')
    return files


def context(args):
    files = source_files(args.source, args.task)
    profiles = [dict(slot=slot, **profile(p)) for slot,p in files]
    result = dict(schema='ssr-task-context/1', task=args.task, sources=profiles,
                  backend_sha256=fingerprint(), task_admission='NOT_RUN', tools=tools(args.task))
    formulas = dict(invsqrt='Q * expected charged cost including rotation synthesis',
                    dqi='repetition_factor * Q^2 * mean_Toffolis',
                    chemistry='lambda_eff * full_model_Q * full_model_Toffolis')
    result['objective'] = formulas[args.task]
    if args.task == 'dqi':
        q = profiles[0]['num_qubits']
        result['width_trade'] = [
            dict(target_Q=n, maximum_Toffoli_factor_at_fixed_failure_factor=(q/n)**2,
                 portfolio_score_factor_at_fixed_T_and_failure=(q/n)**(2/3))
            for n in sorted({q-1, q-2, max(1,q-12)}, reverse=True) if 0 < n < q]
        result['next_question'] = 'Identify values present at every binding peak; price retirement/rebuild before assuming a narrower header is safe.'
    if args.task == 'chemistry':
        path = Path(args.words) if args.words else Path(args.source)/'submission.npz'
        words, binding = word_table(path)
        result['words'] = binding
        result['support'] = 'both actual previous/current assembled word batches and coherent span; not arbitrary incoming words'
        result['full_model_cost'] = None
        result['next_question'] = 'Bind assembled words and source bytes; inspect supplied functions before changing intermediates or table.'
    return result


def handle(rule, source, bound_sha=None, **fields):
    value = dict(schema='ssr-rule-handle/1', rule=rule, source_sha256=bound_sha or sha(source),
                 source=str(Path(source).resolve()), backend_sha256=fingerprint(), **fields)
    value['id'] = seal(value)
    return value


def quick(source, max_events):
    from ssr.rules import zero_control_cx, disjoint_involutions
    k = K.read(str(source))
    end = len(k.op_types)
    k.raw._mmap.close()
    bound = sha(source)
    z = zero_control_cx.scan(Path(source), end, (0,end), max_events, event_kinds=('CCX','CCZ','CSWAP'))
    pairs = disjoint_involutions.scan(Path(source))
    if z['source_sha256'] != bound or pairs['source_sha256'] != bound or sha(source) != bound:
        raise ValueError('source changed during census')
    hs = []
    for e in z['events']:
        if e['kind'] in ['CCX','CCZ','CSWAP']:
            hs.append(handle('initialized-zero', source, bound_sha=bound, event=e,
                             assumptions='unnamed quantum workspace initially zero; named input registers arbitrary'))
    for kind, e in pairs['first'].items():
        if kind in ['CCX','CCZ','CSWAP']:
            hs.append(handle('disjoint-involution', source, bound_sha=bound, event=e,
                             assumptions='exact unconditional pair across a disjoint unchanged corridor'))
    return dict(zero=z, pairs=pairs, handles=hs)


def supplied_scan(source, words_path, slot):
    source = Path(source)
    words, binding = word_table(words_path)
    source_sha = sha(source)
    k = K.read(str(source))
    try:
        if len(k.op_types) > 100000:
            raise ValueError('supplied-context frontend supports at most100000 source operations')
        registers = {n:[q for isq,q,_ in ms if isq] for n,ms in k.registers}
        if any(not isq for n,ms in k.registers for isq,q,_ in ms):
            raise ValueError('chemistry public registers must be quantum')
        rows = list(operations(k))
        parent = chemistry.create(registers, k.num_qubits, words, slot)
        model = chemistry.create(registers, k.num_qubits, words, slot)
        expected = chemistry.swapped(parent, registers)
        for at,row in enumerate(rows):
            parent.step(row, at, search=False)
        if parent.values != expected:
            raise ValueError('parent does not implement the declared assembled-word endpoint map')
        result = model.scan(rows)
        hs = []
        if result['status'] == 'SUPPLIED_FUNCTION_EDIT':
            hs.append(handle('chem-current-parity', source, bound_sha=source_sha, slot=slot, word_file=binding,
                             context=model.contract, candidate=result['candidate'],
                             assumptions='actual adjacent word endpoints, zero workspace; unchanged prior phase and measurement history'))
        result.update(source_sha256=source_sha, words=binding, slot=slot, handles=hs,
                      parent_value_map='exact both endpoints', task_admission='NOT_RUN',
                      num_qubits=k.num_qubits, num_bits=k.num_bits)
    finally:
        k.raw._mmap.close()
    if sha(source) != source_sha:
        raise ValueError('source changed during supplied-context proof')
    return result


def scan(args):
    if not 1 <= args.max_events <= 1024:
        raise ValueError('max-events must be1..1024')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    files = source_files(args.source, args.task)
    reports, hs = [], []
    use_supplied = args.rule == 'supplied' or (args.rule == 'auto' and args.task == 'chemistry')
    words = Path(args.words) if args.words else Path(args.source)/'submission.npz'
    if use_supplied and args.task != 'chemistry':
        raise ValueError('supplied word context requires task chemistry')
    for source_slot,p in files:
        slot = source_slot if source_slot is not None else args.slot
        prefix = 'source' if slot is None else 'slot-'+str(slot)
        try:
            if use_supplied:
                if slot is None:
                    raise ValueError('single chemistry KMB needs --slot')
                r = supplied_scan(p, words, slot)
            else:
                r = quick(p, args.max_events)
            write(out/(prefix+'.json'), r)
            for h in r['handles']:
                write(out/('handle-'+str(len(hs))+'.json'), h)
                hs.append(h)
            reports.append(dict(slot=slot, source=str(p.resolve()), sha256=sha(p),
                                status=r.get('status', 'CENSUS_COMPLETE'), handles=len(r['handles'])))
        except supplied.Unsupported as e:
            r = e.report
            write(out/(prefix+'.json'), r)
            reports.append(dict(slot=slot, source=str(p.resolve()), sha256=sha(p),
                                status='UNSUPPORTED_CONTEXT', reason=r['reason']))
    result = dict(schema='ssr-task-scan/1', task=args.task, sources=reports, handles=len(hs),
                  backend_sha256=fingerprint(), task_admission='NOT_RUN', candidate_is_task_gain=False)
    write(out/'result.json', result)
    return result


def construct(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    source = Path(args.source)
    h = json.loads(Path(args.handle).read_text())
    if h.get('id') != seal(h) or h['source_sha256'] != sha(source):
        raise ValueError('stale or altered source handle')
    if h['backend_sha256'] != fingerprint():
        raise ValueError('backend changed; recensus before construction')
    if h['rule'] == 'chem-current-parity':
        if not args.words or sha(args.words) != h['word_file']['sha256']:
            raise ValueError('word-file binding changed')
        words, binding = word_table(args.words)
        k = K.read(str(source))
        try:
            regs = {n:[q for isq,q,_ in ms if isq] for n,ms in k.registers}
            m = chemistry.create(regs, k.num_qubits, words, h['slot'])
            at = h['candidate']['at']
            rows = list(operations(k, stop=at+1))
            for j,row in enumerate(rows[:-1]):
                m.step(row,j,search=False)
            m.validate(rows[-1],h['candidate'])
            def text(r):
                return r['name']+' '+ ' '.join('q'+str(q) for q in r['q'])
            rhs = '; '.join(text(r) for r in h['candidate']['replacement'])
            script = 'replace '+str(at)+':'+str(at+1)+' => '+rhs+'\n' if rhs else 'delete '+str(at)+':'+str(at+1)+'\n'
        finally:
            k.raw._mmap.close()
    else:
        r = quick(source, 1024)
        expected = [x for x in r['handles'] if x['rule'] == h['rule'] and x['event'] == h['event']]
        if not expected:
            raise ValueError('rule obligation is not reproduced by this source')
        if h['rule'] == 'initialized-zero':
            ops = [h['event']['op']]
        else:
            ops = [h['event']['first'],h['event']['second']]
        script = ''.join('delete '+str(i)+':'+str(i+1)+'\n' for i in sorted(ops))
    (out/'edit.qed').write_text(script)
    result = dict(schema='ssr-rule-construction/1', source_sha256=h['source_sha256'],
                  rule=h['rule'], handle_id=h['id'], obligations='reproved',
                  edit_script=script, edit_script_sha256=sha(out/'edit.qed'),
                  backend_sha256=fingerprint(), task_admission='PENDING',
                  evidence='exact rule theorem under declared source/context assumptions',
                  quantum_header_delta=0, classical_header_delta=0)
    if args.emit_child:
        from ssr.components.materialize import materialize
        result['materialization'] = materialize(source, script, args.emit_child)
    if sha(source) != h['source_sha256']:
        raise ValueError('source changed during construction')
    write(out/'proof.json', result)
    return result


def width(args):
    import numpy as np
    from .liveness import invoice
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    try:
        result = invoice(args.source, args.chunk_ops, args.max_intervals)
        result['register_count'] = len(result.pop('registers'))
        rows = result.pop('intervals')
        table = np.asarray([[q,s,e,int(kind == 'reset')] for q,s,e,kind in rows], dtype=np.int64).reshape(-1,4)
        peaks = np.asarray(result.pop('peak_segments'), dtype=np.int64).reshape(-1,2)
        runs = np.asarray(result.pop('peak_runs'), dtype=np.int64).reshape(-1,2)
        np.savez_compressed(out/'intervals.npz', intervals=table, peak_segments=peaks, peak_runs=runs)
        result.update(schema='ssr-width-invoice/1', backend_sha256=fingerprint(),
                      interval_count=len(table), peak_segment_count=len(peaks), peak_run_count=len(runs),
                      first_peak_runs=runs[:16].tolist(), artifact='intervals.npz',
                      artifact_sha256=sha(out/'intervals.npz'),
                      interval_columns=['wire','start_inclusive','end_inclusive','ends_with_unconditional_reset'],
                      peak_columns=['start_inclusive','stop_exclusive'], task_admission='NOT_RUN',
                      next_question='Inspect a binding peak, prove a value may retire, price recreation at every peak.')
        write(out/'result.json', result)
        return result
    except Exception as exc:
        write(out/'failure.json', dict(status='error', error=str(exc), task_admission='NOT_RUN'))
        raise


def loans(args):
    from .park import census
    import numpy as np
    report=Path(args.width_invoice)
    data=json.loads(report.read_text())
    if data.get('schema')!='ssr-width-invoice/1' or data['source_sha256']!=sha(args.source):
        raise ValueError('width invoice source/schema mismatch')
    artifact=report.parent/'intervals.npz'
    if sha(artifact)!=data['artifact_sha256']:
        raise ValueError('width artifact digest mismatch')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    try:
        with np.load(artifact,allow_pickle=False) as z:
            peaks=z['peak_runs'].copy()
        result=census(args.source,peaks,args.max_handles)
        handles=result.pop('handles')
        write(out/'handles.json',dict(schema='ssr-product-loan-handles/1',source_sha256=result['source_sha256'],handles=handles))
        result.update(handle_count=len(handles),width_invoice_sha256=sha(report),
                      handles_sha256=sha(out/'handles.json'),backend_sha256=fingerprint())
        write(out/'result.json',result)
        return result
    except Exception as exc:
        write(out/'failure.json',dict(status='error',error=str(exc),task_admission='NOT_RUN'))
        raise


def chemistry_relations(args):
    from . import relations
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    try:
        words,binding=word_table(args.words)
        bound=sha(args.relations)
        text=Path(args.relations).read_text()
        rules=relations.parse(text,bits=args.word_bits,columns=words.shape[1])
        result=relations.check(words,rules,bits=args.word_bits)
        if sha(args.relations)!=bound or sha(args.words)!=binding['sha256']:
            raise ValueError('constraint inputs changed during check')
        result.update(words=binding,relations_sha256=bound,backend_sha256=fingerprint())
        write(out/'result.json',result)
        return result
    except Exception as exc:
        write(out/'failure.json',dict(status='error',error=str(exc),task_admission='NOT_RUN'))
        raise


def dispatch(args):
    if args.command == 'chemistry-relations':
        return chemistry_relations(args)
    if args.command == 'loans':
        return loans(args)
    if args.command == 'width':
        return width(args)
    if args.command == 'tools':
        return tools(args.task)
    if args.command == 'context':
        result = context(args)
        write(args.out, result)
        return result
    if args.command == 'scan':
        return scan(args)
    return construct(args)
