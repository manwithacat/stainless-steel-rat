# Task context and constructive entry points

These additions are on the development branch. They require NumPy and a KMB
source; native simulation and task admission remain separately configured.
Start here when the task is DQI or chemistry, or when the full native Rat loop
would build an unnecessarily large operation graph.

```sh
ssr-rat doctor
ssr-rat tools --task dqi
ssr-rat context --task dqi --source source.kmb --out runs/context.json
ssr-rat width --source source.kmb --out runs/width
ssr-rat loans --source source.kmb --width-invoice runs/width/result.json --out runs/loans
ssr-rat scan --task dqi --source source.kmb --rule quick --out runs/quick
ssr-rat construct --source source.kmb --handle runs/quick/handle-0.json \
  --out runs/build --emit-child runs/child.kmb
```

Each output path must be fresh. Source hashes and backend fingerprints are
recorded. Construction reproves a handle against the source and refuses changed
code, changed source, altered truth tables and false identities. The CLI returns
JSON and a nonzero exit status for a refusal. Keep failed output directories.

`context` reports static counts, registers, guard depth and the actual task
objective. It never invents an expected Toffoli count or a repetition factor.
For DQI, width exchange rates assume the failure factor stays fixed; validate
that assumption on the complete decoder. Static counts of guarded gates are
not expected charged counts.

`quick` can construct initialized-zero deletions and disjoint involution-pair
cancellations. Unnamed quantum scratch is assumed initially zero and named
quantum registers are arbitrary. This assumption must match the caller's ABI.
The zero screen forgets uncertain writes; a null only closes this conservative
menu. The pair detector currently exposes the first handle per gate kind.

## Width: distinguish pressure from a retirement proof

`width` scans in bounded chunks and stores full scratch intervals and every
binding peak in `intervals.npz`. It pins named quantum registers throughout,
splits intervals only at unconditional top-level R/HMR, and assumes unnamed
scratch starts and ends zero on the relevant task support. Its peak is exact
for that interval model. It can miss algebraic uncomputation, conditional
zero facts and input registers temporarily available as scratch. It is not a
lower bound on an optimally encoded circuit. No lower-width KMB is emitted.

`loans` reads that source-bound invoice and finds idle scratch holding a product
of two physical controls, optionally complemented or copied. Both controls'
write versions must stay unchanged, and both insertion cuts must be outside
captured condition scopes. The proposed identity measures the product out,
repays its phase with a classical-controlled CZ (and NEG for a complemented
product), and rebuilds with one CCX plus optional X. It needs no extra quantum
wire and one fresh private classical record. It preserves the quantum map after
tracing that private record; it does not preserve an observable aligned record.

This command is **a census only**: individual handles do not establish a joint
schedule, a complete peak cover, a valid record extension, a narrower binary or
a task gain. Two loans can interfere if either borrows the other's control.
The matcher deliberately misses formulas whose controls change and later return.
Use its named controls and cuts to plan a separately proved construction.

## Chemistry: exact supplied-word identities

```sh
ssr-rat context --task chemistry --source family --out runs/chem-context.json
ssr-rat scan --task chemistry --source family --rule supplied --out runs/chem-scan
ssr-rat construct --source family/angle_k_1.kmb \
  --handle runs/chem-scan/handle-0.json --words family/submission.npz \
  --out runs/chem-build --emit-child runs/chem-child.kmb
```

A family contains contiguous `angle_k_0.kmb` through `angle_k_K.kmb` and an
NPZ with explicit, already assembled `angle_words`. For one KMB, pass `--slot`
and `--words` to `scan`. KMX is source assembly: first serialize it with a trusted
kickmix installation and record both the assembly SHA and the resulting KMB SHA.
The portable tools never execute builder source or guess how a factorization's
raw words are assembled.

Register names are `selection` and `word_0` through `word_4`. The five words
must share a width of 1–8 bits, with at most 2,048 addresses and 128 quantum
wires. The source is checked against both actual adjacent word endpoints with
zero workspace before searching. This supports the endpoint swap/involution
ABI, not arbitrary incoming words. Exact current-wire truth functions can
replace a CCX with XORs of available physical wires plus a constant. The parent
map is checked first, all previous measurement-dependent dirty facts remain
explicit, and unsupported data guards or products refuse. Diagonal/measurement
history remains unchanged; this is not a new chemistry fit or a full-family
cost/residual check.

## Whole-task admission

For invsqrt, configure `SSR_ENGINE_PYTHON` to the directory containing
`kickmix_engine` and `SSR_INVSQRT_VERIFIER` to your task specification. Doctor
reports what is available. A native invocation also needs its durable run:

```sh
ssr-rat --run runs/native admit --source child.kmb --parent source.kmb \
  --out runs/native-admission.json
```

DQI and chemistry task verifiers are not shipped here. Take candidates to the
caller's task-specific gate: compare DQI failures and expected charge on paired
inputs, and check the complete chemistry family, numerical residuals and joint
cost. Component equivalence, a width census, a lower static gate count and a
complete local null all have narrower meanings.

For construction beyond a fixed loader, read [chemistry methods](CHEMISTRY_METHODS.md).
The supported `chemistry-relations` command checks the supplied integer words
against mask/F/B/composed-G targets. It does not run the staged rounder, infer
numerical validity, or claim a new table has the same compiled cost.

### DQI initialized six-bit inverse

Use `ssr-rat inverse-channel --source OLD.kmb --candidate NEW.kmb --out receipt.json`
on two standalone normalized leaves with q0–5 holding the source, q6–11 fresh
for the output, and every remaining qubit initially zero. All three physical
record bits enter arbitrary and return jointly uniform. The command checks
all 64 inputs, every affine measurement phase coefficient, an injective
quantum frame after each measurement, and the rank of the returned records.
It reports the two component widths and charges. Matching the caller's
physical ports, allocating the scratch at the call site, and measuring the
DQI expected cost are separate steps.
