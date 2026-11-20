# Release checks

## 0.4.0 (20 November 2026)

The configured suite passed 153 tests and 10 subtests, with one skip. An
offline build produced a 0.4.0 wheel. From a fresh installation, the DQI
menu exposed `inverse-channel`. The installed command reproduced the
19→18 and 20→18 Toffoli comparisons and rejected a leaf with an incompatible
classical interface. These comparisons used externally supplied leaves and
ran without importing the native engine. The component receipts cover all
64 field inputs under the initialized interface described in the
[task guide](TASK_ENTRY.md#dqi-initialized-six-bit-inverse). Their counts
apply to the leaf. A leaderboard claim requires whole-circuit evaluation.

## 0.3.0 release checks

18 November 2026. The production package was frozen and tested in a
network-disabled sandbox with isolated Python, source/runtime hashes and a
1.5 GiB aggregate RSS limit. All workers exited, with no source drift.

| Gate | Result |
| --- | --- |
| Full suite with external kickmix, native engine and invsqrt specification |124 passed,1 optional Z3 skip,10 subtests passed |
| Fresh installed wheel, NumPy and pytest only |58 passed,20 optional dependency skips |
| Installed console entry points from an unrelated working directory |Rat help/doctor and component help/capabilities pass |
| Installed portable examples |Exact reversible and measured comparisons pass |
| Installed native fixture loop |Init, rank query, bad-child rejection, valid park, stale-SHA rejection,4→3 wire recolouring and rollback pass |
| Binary assembly |Streaming output matches the older editor byte for byte, including128-bit angles, tags and registers |
| Adversarial controls |Missing phase repayment, stale nominations, inherited guards, late body target access and outcome-record access are refused or detected |
| Packaging/docs |Wheel builds; Python source parses; local documentation links resolve |

The full suite includes independent scalar/exhaustive controls for measured
instruments and the packed quadratic backend. The long-body frame test crosses
its65536-operation streaming boundary. These are package/correctness checks
on authored fixtures, not a new competition score or a whole-task DQI/chemistry
verifier. Admission's finite outcome schedules remain prescreens.

The public workflow runs the dependency-light suite and a separate wheel
installation on Python3.12 and3.13. Reproduce it using the locked uv setup in
[README](../README.md). To run the optional native tests, provide the external
dependencies listed there; `ssr-rat doctor` reports their configuration.
