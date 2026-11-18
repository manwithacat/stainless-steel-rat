# Portable component workbench

These tools work after installing the Rat with NumPy. They do not need
kickmix, the Rust engine, a competition verifier or the original research
checkout. They inspect KMB directly and also accept JSON lists of literal
operations. Use them for DQI, chemistry and invsqrt components; task-specific
whole-circuit acceptance and pricing are separate.

```sh
ssr-components capabilities
ssr-components compare --backend reversible \
  --source examples/reversible-source.json \
  --candidate examples/reversible-child.json --out runs/reversible.json
ssr-components compare --backend measured \
  --source examples/measured-source.json \
  --candidate examples/measured-child.json \
  --contract examples/measured-contract.json --out runs/measured.json
```

The examples are authored circuits. The first cancels two CCZs across a wire
permutation, removing two paid gates. The second replaces a CCX before phase
reads and HMR, preserving arbitrary dirty target values and every aligned
measurement outcome. Its static count ties; expected task cost is unavailable
until its actual guards and the whole circuit are evaluated.

For a real KMB, select the source window explicitly:

```sh
ssr-components inspect --source SOURCE.kmb --start 100 --stop 150 --out runs/window.json
ssr-components compare --backend measured --source SOURCE.kmb \
  --start 100 --stop 150 --candidate CHILD.kmb \
  --contract outcomes.json --out runs/proof.json
```

JSON programs are complete bounded local programs. KMB windows preserve the
actual inherited guard stack and every angle bit. Inherited guards are
refused by these local proofs; slicing the text and declaring depth zero
does not establish a caller contract. `--expected-sha256` is available on
inspection, comparison and reversible rewrite commands.

| Backend | Supported contract | Limits and refusals |
| --- | --- | --- |
| reversible | arbitrary dirty-entry Boolean values and exact128-bit phase, including global phase |512ops/128wires,512symbolic terms; no measurement/reset/conditions |
| quadratic | packed exact zero-phase quadratic output map on a fixed interface |2048ops/256wires; affine product controls or supported Boolean simplifications; no phase or records |
| measured | sufficient aligned-outcome instrument equality, immutable PUSH snapshots and mutable/versioned records |512ops/128variables/512terms; explicit outcome map, entry-zero and private-record assumptions; dirty resets refused |

Wire ids are bounded at65535 in the portable CLI. Symbolic growth stops with
`NOT_ENTERED`; it does not yield an inequivalence claim. Comparison exits0
for equivalence,1for a difference and2for unsupported input or an error.
The proof records assumptions, source/candidate hashes, backend hashes and
the separate pending task-admission gate.

A measured contract is:

```json
{
  "zero_qubits": [],
  "private_records": [],
  "outcomes": {"source": {"2": "retired"}, "child": {"2": "retired"}}
}
```

HMR indices are local operation indices in each compared program. Labels
identify independent uniform outcomes, not mutable bit addresses; every
HMR needs exactly one independent label. Shared labels align the two
programs. Extra labels are independent latent outcomes. Entry-zero and
private-record declarations are assumptions that a caller must discharge.
Passing this sufficient proof does not mean it handles every equivalent
measurement decomposition.

## Constructors and full-circuit assembly

Reversible rules emit a proved component:

```sh
ssr-components rewrite --source SOURCE.kmb --start 100 --stop 150 \
  --rule phase-fold --out runs/fold
```

Other supported rules are `conjugate` and `cancel`. The resulting child KMB
is a **component**, with an interface register, not a competition submission.

The phase-demand rule has a source-bound discovery and construction path:

```sh
ssr-components phase-scan --source SOURCE.kmb --out runs/scan.json
ssr-components phase-construct --source SOURCE.kmb --scan runs/scan.json \
  --nominee 0 --out runs/constructed --emit-child runs/full-child.kmb
```

The scanner covers every quantum access and nominates an unconditional CCX,
up to8target Z/CZ phase reads and a matching unconditional HMR within512ops.
The constructor transports the original product through supported affine
control changes, generates the required phase repayment, then runs the exact
measured proof. Unsupported target use, guards, nonlinear transport and
capacity limits are explicit refusals. A static tie is retained only for the
conditional-repayment class; it is not assumed cheaper.

On equivalence it writes the component, outcome contract, `proof.json` and
`patch.qed`. Optional `--emit-child` streams those exact edits into the full
source. It preserves registers, declared widths, untouched operations and
the original angle/tag packets. This materializer supports same-width literal
non-angle edits; it refuses new widths and angle/tag rewrites. It does not
substitute for task verification. Consume the child only with its successful
proof/materialization receipt; partial files are preserved on failure.

For a nominated very long disjoint body:

```sh
ssr-components frame --source SOURCE.kmb --first 100 --hmr 250000 \
  --out runs/frame.json --emit-child runs/retimed.kmb
```

This streams body access checks, proves the small endpoint instrument and
applies the established HMR retiming/CZ repayment. It refuses any body access
to the retired wire or its outcome record, unknown operations and nonempty
endpoint guards. It does not scan for a site or assume that equal RNG seeds
give equal histories after measurement ordering changes.

Port provenance: these reusable cores and independent scalar controls come
from the R pathway's validated component/frame/phase-demand work. They use
the existing P/QHDL reader and serializer. Study-specific benchmarks,
competition data and remote controllers remain in the research repository.
