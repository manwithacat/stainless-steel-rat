# Chemistry construction methods and their interfaces

The portable Rat does not fit a chemistry factorization. It supplies exact
constraint and circuit tools; an external optimizer proposes a new table and
the task verifier decides whether it still computes an admissible model.

The public ThemBones milestone-generator toolkit provides a useful source
pipeline. Its 7-bit methods include continuous fitting, staged rounding with
refits, damage models, relation-aware word selection, fixed-table weight
refitting and loader construction. Missing winning orchestration scripts and
unrecorded fit/search seeds limit replay of the winning run; they do not make
these methods unavailable.

| Stage | Mechanism | Interface and acceptance obligation |
| --- | --- | --- |
| Continuous fit | Fit vectors and weights against the packed two-body residual. | NPZ `U` is `(R,B,76)`, `W` is the two-body weight array `(R,B,C)`. A continuous residual is not a quantized task result. |
| Damage model | Use a Gauss–Newton metric and eliminate compensating variables with a Schur complement. | State angle units, variable order, frozen set and the metric's local validity. Predicted rounding damage is a model, not a numerical gate. |
| Staged rounding | Freeze costly decisions while free angles and weights compensate; preserve code constraints. | Keep row-to-address assignment and the exact frozen integer words in checkpoints. Changing placement changes relation targets. |
| In-stage refit | `StageLM7` backtracks rejected LM steps, carries damping between stages and preserves frozen words and masked weights. | Requires external JAX. Set weight masks before compilation. Record precision, iteration limits, seeds and the complete resume state. |
| Relation placement | Fit address-block target constants, assign rows within their allowed groups, and defer parity debt to still-free words. | Use the complete composed target ABI below. The row assignment, fitted targets and word order must travel together. |
| One-body step | Round and polish the 76 one-body rows under the same target relations and carrier gauge. | A target change fitted on two-body rows must also be followed here. Check both numerical residuals. |
| Fixed-table refit | Optimize weights and channel offsets while keeping angle words fixed. | NPZ `W` and `H2_I` have different roles. Accept on joint task cost and residuals, not just a lower smooth objective. |
| Loader construction | Compile the actual supplied word table, with source-dependent products and free address functions. | Emit KMB; prove the lookup interface, phases and width; price the complete family and model. |

The upstream code uses `theta/pi` in several interfaces and radians inside LM.
A public adapter must make this conversion explicit. A bit width alone does not
define a signed gauge, a carrier convention or a numerical tolerance.

## Exact relation checking available in the Rat

```sh
ssr-rat chemistry-relations --words submission.npz \
  --relations rel_final.txt --word-bits 7 --out runs/relations
```

For loader `k`, `k | j:b ... | target` requires the XOR of the specified bits
of `word[5*k+j] XOR word[5*(k-1)+j]` to equal a target function of the address.
Slots `j` are zero based. The checker supports:

- An integer address-parity mask.
- `F:seed`: the upstream seeded low-address XOR block table.
- `B:x`: constants on blocks 0–3, zero elsewhere.
- `G/base/blockhex[/lowhex]`: any of those bases XOR a block table XOR an
  optional 16-entry low-address table. In particular, `G/F:2150/…` is valid.

The full expression is `base(address) XOR g[address>>4] XOR f[address&15]`.
The earlier WR7 G/int reader is narrower than this ABI. Use the comprehensive
R65 reader when comparing with upstream, and preserve the NumPy runtime for
seeded targets. A constraint violation does not by itself reject a numerical
model or prove that its existing circuit is wrong.

The method family exposes an actionable extension: `RelPlacerGF` fits the low
part as well as the block part. Upstream marks it as not yet connected to the
rounding and one-body pipeline. Its inherited checkpoint saves placement and
`G`, but omits `Fq`; an adapter must save and restore all three explicitly.
A small conditional-rounding model can test this freedom cheaply. Before a
real fit, check a complete emitted loader's resource cost and phase contract,
then connect the one-body step and validate the joint chemistry objective.

Credits: team ThemBones, the public `vqcc-thembones-milestone-generators`
dataset, and its credited upstream authors. The staged-rounding code explicitly
credits Ahmed Berat Özer's progressive rounding and marculera's pipeline.
No upstream fitting code, dataset or winning circuit is bundled in this package.
