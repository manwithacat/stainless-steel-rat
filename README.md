# The Stainless Steel Rat

The Stainless Steel Rat (SSR, or "the Rat") is a toolkit that lets an LLM agent rewrite
[kickmix](https://github.com/quantumlib/Qualtran/tree/main/kickmix) circuits (`.kmb`) safely.
The agent proposes; the Rat builds, checks, records and refuses.

It has two parts:

1. **An agent loop on a native engine.** Every circuit state is stored under its SHA-256. The
   agent observes the current state, spends a small budget of structural queries, and proposes
   guarded rewrite steps. Each candidate is built as a new object and evaluated on every legal
   input before it can become the current state. The Rat keeps the best valid state (the
   *incumbent*) separate from the current one, supports rollback, and writes an append-only
   journal with a receipt for every evaluation.
2. **Rules.** A rule is a repeatable transformation, not a remembered address. Each rule follows
   the same five stages: *census* (find every eligible site, with a handle bound to the source
   SHA) → *obligations* (what must hold for equivalence, with an evidence tier) →
   *construction* (deterministic candidate bytes) → *admission* (whole-circuit and official
   checks) → *controls* (a positive case, a negative case, and a scan of the circuit you care
   about). See [docs/RAT_RULE_CONTRACT.md](docs/RAT_RULE_CONTRACT.md).

The task adapter implemented today is the inverse-square-root phase task (`invsqrt`) from the
Verifiable Quantum Circuit Compilation benchmark: the circuit must apply phase
`exp(2πi·β/√x)` to every input `x`, restore `x`, and return all scratch to zero. The static
queries, the vendored KMB tools and most rules work on any KMB.

There is no learned policy. The tools are agent-directed: an agent (or a person) chooses the
queries and actions, and the Rat enforces the bookkeeping.

## Install

Python 3.12 or later.

```sh
pip install -e .            # numpy only
pip install -e '.[test]'    # adds pytest
```

Three things are optional and not included (see [NOTICE](NOTICE)):

| Dependency | What needs it | How to provide it |
| --- | --- | --- |
| `kickmix` (Google Quantum AI, in Qualtran) | KMB↔KMX conversion, fixtures, most rules | install it into the same interpreter |
| The official invsqrt verifier, `verify_submission_invsqrt.py` | task contract, reference phases, cost formula, the authored fixture | `export SSR_INVSQRT_VERIFIER=/path/to/verify_submission_invsqrt.py` (from the competition data) |
| `kickmix_engine` (separate Rust engine) | native evaluation: `ssr.rat`, `ssr.stream`, `ssr.native`, `ssr.crosscut` | `export SSR_ENGINE_PYTHON=/path/to/kickmix-engine/python` or pass `--engine-python` |

`SSR_KICKMIX_PYTHON` names an interpreter with kickmix for the two helpers that convert formats
in a subprocess (default: the current interpreter). `SSR_INVSQRT_REF_CACHE` optionally names an
`.npz` file used to cache the full 3,133,452-row reference table.

Run the tests:

```sh
python -m pytest -q
```

Tests that need a missing dependency are skipped with the reason. From an uninstalled checkout, run
them from the repo root without `-I`: isolated mode (`python -I`) drops the current directory from
the import path, so `ssr` cannot be imported unless the package is installed.

## Five-minute quickstart (authored fixture)

The fixture is a 4-wire, 2-input toy invsqrt circuit (inputs `x = 1..3`). It is a teaching
circuit, not evidence of anything. Wire `q3` holds a copy of `q0` for most of the circuit, so it
can be measured out and rebuilt later, after which recolouring removes a wire.

```sh
mkdir -p runs
python -m ssr.mouse.fixtures runs/fixture        # writes source.kmb, source.kmx, contract.json
python -m ssr.rat --run runs/demo init --source runs/fixture/source.kmb \
       --contract runs/fixture/contract.json
```

`init` evaluates the source natively and prints the first observation:

```json
{
  "agent": "Stainless Steel Rat",
  "backend": "experimental native",
  "state_sha256": "8ac4fce6642cbaf5f3970736bcc1e35568a6903aa0922c040d61f008978cdbd9",
  "incumbent_sha256": "8ac4fce6642cbaf5f3970736bcc1e35568a6903aa0922c040d61f008978cdbd9",
  "declared_qubits": 4,
  "loss_estimate": 45.63790333539637,
  "acceptance": "all legal inputs under native chunk-seeded7/101; final scratch/input/tolerance; no cumulative dirty-reset check",
  "debt_fraction": 0.05,
  "attempts": 0,
  "evaluations": 1,
  "actions": ["recolour", "reserve_qubits", "advance_hmr", "park_recompute",
              "park_factored", "park_one_scratch", "replace_window"],
  "single_writer_required": true
}
```

Set `S` to the `state_sha256` you see, then look at wire 3 and try a wrong and a right
reconstruction:

```sh
S=8ac4fce6642cbaf5f3970736bcc1e35568a6903aa0922c040d61f008978cdbd9
python -m ssr.rat --run runs/demo query --expected $S --request '{"type":"wire","wire":3}'
python -m ssr.rat --run runs/demo step --expected $S \
  --action '{"type":"park_recompute","wire":3,"after":0,"before":5,"terms":[["q1"]]}'
# {"status": "rejected", "child": "ceed33a4..."}          wrong value: native check fails
python -m ssr.rat --run runs/demo step --expected $S \
  --action '{"type":"park_recompute","wire":3,"after":0,"before":5,"terms":[["q0"]]}'
# {"status": "entered_native_model", "child": "51e7d1c2...", "loss_estimate": 45.637...}
```

The `wire` query shows `q3` written at op 0 and op 5 with an idle gap between them. The parked
state costs the same; it is a stepping stone. Now the current SHA has changed, so the old `$S`
is refused (`"stale state: observe and use current SHA"`). Observe again and recolour:

```sh
S=$(python -m ssr.rat --run runs/demo observe | python -c 'import json,sys;print(json.load(sys.stdin)["state_sha256"])')
python -m ssr.rat --run runs/demo step --expected $S --action '{"type":"recolour"}'
# {"status": "entered_native_model", "child": "d25ef363...", "loss_estimate": 34.228...}
python -m ssr.rat --run runs/demo observe          # declared_qubits 3; incumbent = current
python -m ssr.rat --run runs/demo rollback --expected <current SHA>
# current returns to the parked state (4 qubits); incumbent stays d25ef363...
```

Everything is in `runs/demo`: `objects/` (every state by SHA), `evaluations/` (receipts),
`events/` (the journal) and `attempts/` (each build, including failures). Reopening the run
with any command restores the last checkpoint.

## The core loop, as an agent should run it

1. **init** once per run directory, on a fresh directory. The context (source SHA, task
   contract, engine and code fingerprints, budgets, loss ceiling) is frozen; a different
   contract or changed code needs a new run.
2. **observe**. Read `state_sha256`, `incumbent_sha256`, `loss_estimate`, `attempts`,
   `evaluations`.
3. **query** (`--expected <current SHA>`) to understand structure before editing. Queries never
   change navigation. Budget: 12 per run.
4. **step** (`--expected <current SHA>`) with one typed action. Budget: 8 attempts and 8 native
   evaluations; cached evaluations of an already-seen SHA are free.
5. **evaluate** happens inside `step`: the candidate runs natively on every legal input under
   two seeded measurement schedules. Statuses: `rejected`, `pruned` (valid but above the
   source-anchored loss ceiling, default +5%), `duplicate`, `entered_native_model`,
   `not_entered` (a guard refused it; the error says which).
6. **rollback** (`--expected <current SHA>`) to back out of a branch. The incumbent and all
   receipts survive.

The exact command and action reference to give an agent is
[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md).

## Query catalogue

| Where | Query JSON | Answer |
| --- | --- | --- |
| `ssr.rat`, `ssr.workbench` | `{"type":"overview"}` | declared width, operations, registers, structure |
| `ssr.rat`, `ssr.workbench` | `{"type":"window","start":0,"end":6}` | exact op records, conditions, 128-bit angles (≤256 ops) |
| `ssr.rat`, `ssr.workbench` | `{"type":"wire","wire":3}` | lifetimes, touches, phase uses, idle gaps |
| `ssr.rat`, `ssr.workbench` | `{"type":"peak"}` (optional `start` or `index`) | allocator live peak and wires at it |
| `ssr.workbench` | `{"type":"value","at":1,"wires":[0,3],"level":"full"}` | wire values in three local outcome models |
| `ssr.workbench` | `{"type":"fit_recompute","wire":3,"after":0,"before":5,"basis":[0,1,2],"degree":2,"validation":"full"}` | inferred XOR-of-products expression or counterexample |
| `ssr.workbench` | `{"type":"check_relation", ... ,"terms":[["q1"]]}` | test a supplied hypothesis |
| `ssr.workbench` | `{"type":"trace","x":1,"at":[0,1,6],"wires":[0,3],"level":"full","outcome":"7"}` | one row's values and phase along the run |
| `ssr.workbench` | `{"type":"compare","other_sha256":"<sha>"}` | structure and recorded local losses of two states |
| `ssr.crosscut` | `{"type":"information_boundary","wire":W,"start":I,"stop":J}` | first op where an idle wire stops being determined by the others (22-wire invsqrt only) |

`ssr.workbench` works on a **local BitSim run** made by `python -m ssr.mouse` (same actions,
local outcome models `zero`/`7`/`101` instead of the native engine):

```sh
python -m ssr.mouse --run runs/local init --source runs/fixture/source.kmb \
       --contract runs/fixture/contract.json --sample-rows 3
python -m ssr.workbench --run runs/local --journal runs/local-journal query \
       --request '{"type":"fit_recompute","wire":3,"after":0,"before":5,"basis":[0,1,2],"degree":2,"validation":"full"}'
python -m ssr.workbench --run runs/local --journal runs/local-journal apply-query --id <query_id>
```

`apply-query` submits a validated fit as an action through the local loop; it refuses if the
queried SHA is no longer current. `python -m ssr.native --run RUN --state SHA --rows N --out FILE`
writes a sampled native diagnostic receipt for one stored state without changing navigation.

## Rule tools

All rule tools read a source KMB, never overwrite an output, and bind handles to the source SHA.

| Command | Stage | What it does |
| --- | --- | --- |
| `python -m ssr.crosscut.gap_census SRC.kmb --expected-sha256 SHA` | census | idle gaps covering the allocator peak, ranked; static only |
| `python -m ssr.crosscut.rule SRC.kmb [--fit-index K] [--out F]` | census + obligations | long-gap quadratic reconstruction; the fit returns a `park_factored`/`park_one_scratch` action exact on all legal `x` in three outcome models |
| `python -m ssr.crosscut.information_boundary SRC.kmb --wire W --start I --stop J` | obligations | exact information-loss point for an idle wire |
| `python -m ssr.crosscut.peak_barriers SRC.kmb --run R --out F` | obligations | information-loss operations for idle wires across one peak run |
| `python -m ssr.crosscut.coverage` | planning | optimistic peak-cover lower bound (needs `scipy`) |
| `python -m ssr.rules.quadratic_rank SRC.kmb --out census.json` then `--handle H --out child.kmb` | census + construction | one-target CCX windows rewritten to `rank/2` CCXs, exact on all entry states; `--phase-transparent` keeps non-target phase/measurement ops in place |
| `python -m ssr.rules.target_accumulation SRC.kmb --out census.json` | census | source-bound target-only five-CCX windows for reached-state synthesis; reports arbitrary-entry rank and obligations, emits no candidate |
| `python -m ssr.rules.minand_smt --table TABLE.json --target qN --gates 4 --timeout 120 --out PLAN.json` | bounded synthesis | optional `.[synth]` Z3 search for an AND straight-line program on a reached target-toggle table; checks every supplied row, emits no KMB |
| `python -m ssr.rules.quadratic_null_search SRC.kmb --handle H --out null.json [--beam-width 300]` | finite prescreen | tests whether two physical entry-wire products agree modulo affine terms and lower an accumulation's exact arbitrary-entry rank; optional bounded two-relation beam; no KMB emission |
| `python -m ssr.rules.reader_cut_quadratic SRC.kmb --handle H --trials 128 --refine-support 32 --out reader.json` | finite prescreen | moves the interface to the first target reader, fits a quadratic in physical wires, then searches rank-lowering products of up to two selected wires; reports panel factor count, no KMB emission |
| `python -m ssr.rules.zero_control_cx SRC.kmb` | census | gates provably inert because a control is zero |
| `python -m ssr.rules.zero_control_peak_release SRC.kmb PEAK.json --script E --report R` | construction | reset + deletions releasing a scratch wire across a peak run (edit script) |
| `python -m ssr.rules.disjoint_involutions SRC.kmb --output F` | census | self-inverse gate pairs cancelling across untouched corridors |
| `python -m ssr.rules.nested_involutions SRC.kmb --output F [--script E]` | census + construction | nested cancellations of self-inverse gates |
| `ssr.rules.reachable_cswap` (library: `census`, `delete`) | census + construction | CSWAPs that are no-ops on exact legal inputs in the sampled branches |
| `python -m ssr.rules.clifford_splice --donor D --host H --donor-sha .. --host-sha .. --out F [--emit C]` | construction | splice sibling invsqrt circuits at a common 1,024-op block with free Clifford phase repair |
| `python -m ssr.rules.hmr_stress --candidate C --host H --candidate-sha .. --host-sha .. --out F` | admission prescreen | `x = 1..63` under 67 measurement histories, against an exact integer reference |
| `ssr.rules.portable_hmr.PortableBitSim` | admission prescreen | measurement outcomes keyed by (seed, op, x), stable across input panels |

`PEAK.json` for `zero_control_peak_release` needs `input_sha256`, `run_rows` (`start`, `end`
per run) and `idle_all` (`wire`, `role`, `runs` as `"R0..R3"`); see
`tests/test_rule_zero_control_peak_release.py` for a minimal example.

Edit scripts and edits are applied with the vendored QHDL editor (`ssr/qhdl/edit.py`). A rule's
output is always a *candidate*: feed it to the loop (`replace_window`, or `init` a new run on the
child) and to the verifier.

## Evidence tiers, and what never to claim

| Tier | Produced by | Means |
| --- | --- | --- |
| static | structure queries, census tools | facts about bytes and lifetimes; says nothing about values |
| local prescreen | BitSim models (`zero`, `7`, `101`), `hmr_stress`, rule fits | correct on those inputs and outcome models only |
| native whole-circuit gate | `ssr.rat` / `ssr.stream` evaluation | every legal input under two seeded native schedules; final scratch, input and tolerance; no cumulative dirty-reset check |
| official verifier | the unmodified official verifier, run separately | the task's own acceptance and cost |

Never claim:

* that a candidate is *correct* or *equivalent* from a static query, a sampled fit, or a lower gate count;
* that a Rat `loss` or `loss_estimate` is the official cost. It is the official formula applied
  to fixed local or native schedules, with final-input padding included;
* that "no candidate" from a bounded query means no improvement exists. It covers only that basis,
  degree and budget;
* an official result you did not run. `python -m ssr.mouse ... record-official --report R` only
  attaches an existing report, marked `recorded-not-rerun`, after checking circuit SHA, settings
  and verifier hash.

## Safety rules for agents

* **Bind to the state SHA.** Every indexed query, step and rollback carries `--expected`. If it is
  refused as stale, `observe` and think again; do not retry blindly.
* **Never overwrite.** `init` needs a fresh directory, rule outputs refuse existing paths, and
  objects, receipts and events are append-only. Do not edit run directories by hand.
* **One writer per run.** Do not run two mutating processes against one run directory.
* **Respect budgets.** Queries, attempts and evaluations are capped per run and invalid requests
  count. A budget stop is not a dead end.
* **Keep failures.** Rejected candidates and guard errors are evidence; report them.
* **Change of code or contract means a new run.** Context fingerprints bind the code; reopening
  with changed code is refused.

## Limitations

* No learned or automatic search policy beyond a small automatic menu in the local loop
  (`python -m ssr.mouse ... explore`, recolour and HMR advances only). Park expressions and
  windows come from the agent or a rule.
* One task adapter (`invsqrt`, at most 22 input wires). The exact-domain crosscut queries need the
  full 22-wire task.
* Native acceptance uses two seeded schedules per input, not all measurement histories, and has
  no cumulative dirty-reset check.
* Local BitSim and native engine use different random-number schedules and phase arithmetic;
  receipts from one never satisfy the other.
* The official verifier is not shipped; you must supply it.

## Package layout

```
ssr/qhdl/       vendored QHDL core: KMB I/O, bitset simulator, lifetime allocator, editors
ssr/mouse/      state store, guarded actions, local invsqrt evaluator, local loop CLI, fixture
ssr/workbench/  read-only investigation journal over a local run
ssr/native/     native engine probe
ssr/stream/     first native loop (streaming evaluator)
ssr/rat/        the Rat: native loop with static queries (main agent CLI)
ssr/crosscut/   cross-cut reconstruction rule, information boundary, gap census
ssr/rules/      other rules and prescreens
docs/           rule contract, agent guide
tests/          authored-fixture tests
```

## Credits and licence

Written by the "R" research pathway (ChatGPT, run by James Barlow / manwithacat) of a Verifiable
Quantum Circuit Compilation project. The QHDL core in `ssr/qhdl/` comes from the same project's
Claude pathway. kickmix is by Google Quantum AI; the kickmix engine is a separate project.

Copyright 2026 James Barlow. Licensed under the Apache License, Version 2.0; see
[LICENSE](LICENSE) and [NOTICE](NOTICE).
