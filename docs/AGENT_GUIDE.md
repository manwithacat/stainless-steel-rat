# Agent guide: operating the Rat through its CLI

This page is the short protocol to hand an agent that operates a Rat run. Start with `ssr-rat doctor`. The native loop needs kickmix, `SSR_INVSQRT_VERIFIER` and `SSR_ENGINE_PYTHON`; the [component workbench](COMPONENTS.md) needs only NumPy and is available before native setup.

For DQI/chemistry entry, source-bound construction, or a large decoder whose
operation graph would exceed memory, use the [task entry](TASK_ENTRY.md).
`ssr-rat tools --task dqi` distinguishes context, census, construction and
whole-task gates. Those portable commands do not need `--run` or an engine.

## Command prefix

```sh
python -m ssr.rat --run RUN_DIR <command>
```

Commands:

```
init --source CIRCUIT.kmb [--contract CONTRACT.json]
observe
query    --expected SHA --request JSON
step     --expected SHA --action JSON
rollback --expected SHA
census --source SOURCE.kmb --points 817 --out census.json
admit --source CHILD.kmb --parent PARENT.kmb --out admission.json
```

Every command reopens the durable run directory. Take `state_sha256` from `observe` and pass it as `--expected`; a stale SHA is refused, so an indexed edit can never land on a state you did not look at. A run allows up to 12 queries, 8 attempts and 8 native evaluations (invalid queries count too). Use one writer per run directory.

## Static queries (structure only; never a proof of values)

```
{"type":"overview"}
{"type":"window","start":I,"end":J}      0-based operations, end exclusive, at most 256
{"type":"wire","wire":W}                 lifetimes, touches, phase uses, idle gaps
{"type":"peak"}                          allocator live peak; optional "start" or "index"
```

## Actions

```
{"type":"recolour"}
    Reuse scratch wires by certified lifetimes; input registers stay pinned.
{"type":"reserve_qubits","num_qubits":N}
    Raise declared width by 1..16 with a header-only edit (an intermediate state, never an improvement).
{"type":"advance_hmr","op":I,"after":J}
    Move an existing unconditional HMR earlier across disjoint uses.
{"type":"park_recompute","wire":W,"after":I,"before":J,"terms":[["q0"],["q1","q2"],["1"]]}
    Measure W out after op I, rebuild it before op J as an XOR of products, with phase repair.
    W must be idle in the gap; both boundaries outside condition blocks.
{"type":"park_factored", ...} / {"type":"park_one_scratch", ...}
    Factored reconstructions using 2 / 1 dead scratch wires. Take these from
    `python -m ssr.crosscut.rule SOURCE.kmb --fit-index K` ("fit_result"."action"); do not hand-write them.
{"type":"replace_window","start":I,"end":J,"ops":["CX q0 q2", "@K"]}
    Bounded splice (at most 256 ops). Copy unchanged angle-bearing ops with the string "@K".
```

Construction guards check syntax, condition depth, idleness and lifetimes. They do not prove the reconstruction is right. Admission v2 checks every legal input under zero/7/101 with cumulative dirty resets, prices the exact official schedule through our engine, and requires a parent-bound activating-subspace transition screen. INCONCLUSIVE cannot enter the Rat. These outcome samples are not an all-history proof.

Before a park fit, use `{"type":"rank_liveness","points":64}`. Full affine rank rules out a free affine recovery at that interface; it leaves nonlinear rebuilds eligible. Standalone `census` avoids initializing a full Rat run. See [admission and census](ADMISSION_AND_CENSUS.md) for commands, cut semantics, witness scope and cost calibration.

## Reading results

* `step` returns `status`: `rejected` (native check failed), `pruned` (valid but above the source-anchored loss ceiling), `duplicate`, `entered_native_model` (now current), or `not_entered` with an error from a guard.
* Entering a state is not the same as improving. `observe` reports `state_sha256` (where you are) and `incumbent_sha256` (best valid state seen). A cost tie leaves the incumbent unchanged.
* `rollback` moves `current` back one step; the incumbent and every receipt stay.
* Rejected candidates stay in the journal on purpose.

## What to report

Your query and action decisions and why, each acceptance or rejection, the final current and incumbent SHA, and anything confusing. State the evidence tier: v2 `loss_estimate` is the engine reproduction of the default-salt official schedule/formula, not an official-simulator or hosted result. Legacy stream/local losses keep their original sampled meaning.
