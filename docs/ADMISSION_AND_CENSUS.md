# Admission and live-value census

Use `census` to decide whether a free affine reconstruction is worth trying.
Use `admit` to check a built candidate and its price. Neither command supplies
a search policy or an exhaustive proof over measurement histories.

The environment is the same as the README. From an installed checkout:

```sh
python -m ssr.rat --run runs/rank census --source SOURCE.kmb \
  --points 817 --panel-rows 4096 --out rank.json
python -m ssr.rat --run runs/gate admit --source CHILD.kmb \
  --parent PARENT.kmb --out admission.json
python -m ssr.rat --run runs/targeted admit --source CHILD.kmb \
  --parent PARENT.kmb --transition-only --out transition.json
```

These standalone commands do not initialize or navigate a Rat run. Each output
path must be new. `admit` exits 1 for a semantic rejection or incomplete
activation coverage, 2 for a usage error. `census` needs kickmix and the task
contract, but does not need the Rust engine. Both accept `--contract FILE`.
Run them within the calling project's resource and sandbox policy.

In a live Rat run, the query is:

```json
{"type":"rank_liveness","points":64,"panel_rows":4096}
```

An optional `"cuts":[123,456]` selects explicit boundaries instead of peak
sampling. Pass the current SHA through `--expected` as with other queries.
Live queries return counts and at most six example cuts; full rows are saved
under the run's `investigations/`, with path and SHA in the reply.
The default panel is deterministic integer linspace from 1 to max_x, with
outcomes zero/7/101. Values are taken **before** each selected op. Static
occupancy includes the first and last touches/reset, and input wires stay
pinned; an allocation endpoint can therefore include a newly initialized zero
wire. This is an interface/value screen, not a physical width certificate.

`linear_rank` is the ordinary column rank. `affine_rank` is
`rank([1, live values]) - 1`. For example, q1=q0 XOR 1 has linear rank two
and affine dimension one. A full-rank panel supplies a counterexample to
every proposed affine identity on that interface under that schedule. The
report counts such cuts as `free_affine_candidate_windows_filtered`. It never
filters paid `park_recompute`, factored rebuilds or interface changes. A
reported XOR witness holds only on the panel; validate it over the full
legal domain and relevant outcomes before using it.

Admission v2 has separate layers:

1. BitSim executes every legal x under zero and two independent random
   schedules, checking restored input, final scratch, phase tolerance and
   cumulative dirty resets at every executed R. Clean final scratch cannot
   hide an earlier dirty reset.
2. A transition aligns parent and child measurement variables and drives the
   activation conditions of changed guarded operations. It compares exact
   final phase/state under those samples and audits both task contracts and
   dirty resets. Skipped, unknown or unactivated targets are INCONCLUSIVE and
   cannot enter the Rat. This is sampled activation coverage, not enumeration
   of every outcome assignment. Some distributionally valid measurement
   rewrites may fail the aligned-outcome requirement; that is a conservative
   limitation of this admission path.
3. Our Rust task engine uses the unchanged official equations and the exact
   default-salt shot/seed/chunk schedule (64 shots per x in the competition).
   `loss_estimate` is this engine reproduction of the cost, not a padded
   two-seed estimate or a fresh official-simulator result. It still refers to
   one salt. Synthetic contracts must have max_x*shots_per_x divisible by 256;
   the adapter refuses to substitute padding.

Native Rat contexts now use `ssr-native-rat/2`. Start a fresh run when upgrading;
old receipts and the `ssr.stream`/`ssr.rat.stream` diagnostic models remain
available with their original evidence scope. Source and backend hashes bind
receipts, and transition receipts also bind the parent SHA. Initial source
admission has no parent comparison and explicitly reports finite outcomes.

## Calibration

Preregistered X-0112/X-0113 local controls (17 November): HW25 cost
93863.3572624325 and HW26 cost 78673.56921101942 reproduce the known official
fixtures with absolute difference zero through our engine, 200,540,928 shots
each. The targeted screen rejects faulty 13e23a0d71c2 against bbfa9675880e:
1,628 phase failures, first x=65; zero and two ordinary schedules miss them.
The bounded-memory retry takes 23.12 seconds and peaks at 819MB.

For the 46Q Syed Asad Ali / Ali Haydar Özdağ / Atakan Aldemir source
dcde70780434, the fixed linspace panel finds full affine rank at 272/817 sampled
peak boundaries (33.29%). These 272 windows are filtered from free affine
recovery only; the other 545 remain unresolved. This is not a reproduction of
another team's 787/817 with an unspecified panel. Full Rat tests: 104 passed,
one optional Z3 test skipped, 10 subtests passed. No claimed competition gain
follows from either tool; they improve rejection and search triage.
