# Working with the Rat

For task-specific context and large-circuit pressure, read
[the portable task entry](docs/TASK_ENTRY.md) and run `ssr-rat tools --task TASK`.
Its width/product-loan censuses do not construct a joint lower-width circuit.

Start with `ssr-rat doctor` and `ssr-components capabilities`, then read
[the agent guide](docs/AGENT_GUIDE.md). The component tools require NumPy;
the invsqrt task loop also needs kickmix, the separate Rust engine and your
copy of the official task specification. Doctor reports those dependencies.

For a bounded circuit core, use `ssr-components inspect`, then compare or
construct a candidate through the documented backend. Reversible, quadratic
and measured proofs have different contracts; an unsupported/capped proof
is not a counterexample or an optimization lower bound. Preserve exact
128-bit angles, guard snapshots, record interfaces and dirty-entry facts.

Bind every edit to source bytes. Use fresh output paths; preserve failures.
In a Rat run, observe the current SHA before query/step/rollback. Whole-task
admission remains separate from component equivalence. Invsqrt native
admission covers all legal inputs under the listed schedules, including
cumulative dirty resets; finite outcome samples are not an all-history proof.
This release does not ship DQI or chemistry whole-task verifiers.

Run `python -m pytest -q -rs` before changing a supported rule. Optional native
tests skip when their external dependencies are absent. Follow the user's
authorization for publication and Git actions. Do not add competition data,
credentials or machine-specific research drivers to this public package.
