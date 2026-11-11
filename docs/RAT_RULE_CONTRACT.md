# Rat rule contract

An EDA-style rule is a repeatable transformation, not a remembered circuit address. Every new Rat heuristic should expose these stages:

1. **Census.** A deterministic matcher reads exact source bytes, returns every eligible site and a handle bound to source SHA, site address and matched content. The matcher states the syntax/semantic family it covers. No candidate is built by a census.
2. **Obligations.** The rule lists conditions needed for equivalence: reachable values at cuts, zero/dirty status, classical measurement-bit lifetime, phase byproducts, register restoration and any extra scratch. Each condition has an evidence tier. A sampled fit is a proposal, not a proof.
3. **Construction.** Given source and handle, the rule deterministically emits a candidate, edit provenance, resource changes and exact-angle preservation. It refuses stale handles and failed obligations. Repeated application to the same source and handle should produce the same bytes under the same tool version.
4. **Admission.** The native whole-circuit gate checks the task contract; the official verifier and an expected-cost comparison decide whether a candidate is worth anything. A local identity or a lower static gate count alone does not promote a candidate. Record the verifier's *error counts and repetition factor*, not just its `PASS` field: a verifier that tolerates a small failure rate can pass a circuit with rare new value errors that still worsen its cost. When a rewrite claims exact equivalence, any new error rejects that claim even if the verifier accepts the circuit. For a hash-seeded verifier, rerun the parent with the child's explicit seed to tell a source error from a child-induced error, then replay the exact failing batch before changing the rule.
5. **Controls.** One known-good positive case, one obligation-breaking negative case, and a scan of the circuit you actually care about (your current best). A positive on a historical circuit establishes capability only; report separately whether the current best changes.

The agent may decide which rule to investigate, choose among matched sites, or propose a new relation. Once a relation is useful, encode its detector, proof obligations and constructor so the Rat can reapply it opportunistically.

## Why admission is a separate stage

A relation can hold on tens of thousands of legal samples, and the resulting candidate can be reported `PASS` by a verifier, yet an exact replay of the verifier's own input draw can still find a single input that causes a new value error. Such a rule is rejected. Sampled agreement is evidence for a proposal, never for equivalence. When this happens, locate the first failing batch under the candidate's own verifier seeds, compare it with the parent on the same batch, and keep the failing case as a regression fixture.

## Rules shipped with this package

* `ssr.rules.zero_control_cx CIRCUIT.kmb` is a source-independent, conservative matcher for CX, CCX, CCZ and CSWAP gates that are provably inert because a control operand is zero. It reports reset provenance and forgets the zero fact after any uncertain mutation; it does not edit the KMB. The matcher and an edit are separate admission stages.
* `ssr.rules.zero_control_peak_release CIRCUIT.kmb PEAK.json --script edits.qed --report receipt.json` is the construction half for peak reports. It selects peak runs with exactly one idle scratch wire, certifies a second wire as zero at entry and touched only by no-op CX controls, then emits a reset and the corresponding deletions as an edit script. It refuses insertion inside a classical condition scope. Width may stay the same while peak occupancy falls; only whole-circuit verification and a fresh peak analysis say what changed.
* `ssr.rules.disjoint_involutions` and `ssr.rules.nested_involutions` find self-inverse gate pairs that cancel exactly across corridors whose operands are untouched in between.
* `ssr.rules.quadratic_rank` rewrites one-target CCX windows to the exact quadratic-rank floor (see the README).
* `ssr.rules.reachable_cswap` deletes CSWAPs that are no-ops on every exact legal input in the sampled measurement branches.
* `ssr.crosscut.rule` proposes long-gap quadratic reconstructions for the guarded `park_factored` / `park_one_scratch` actions.
* `ssr.rules.clifford_splice` splices two sibling invsqrt KMBs at a common block and repairs the phase with free Clifford gates; `ssr.rules.hmr_stress` is its many-history prescreen.
