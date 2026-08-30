# External assembly classification report

Generated: 2026-08-30T14:23:42+00:00

## Coverage

- Downloaded and hash-verified STEP files: 29
- Structurally inspected files: 29
- Admitted assemblies (at least 10 Solid entities): 28
- Large admitted assemblies (at least 50 Solid entities): 21
- Completed Boolean-final assemblies: 22
- Completed rigid-screening assemblies: 0
- Admitted assemblies covered by either tier: 22 / 28
- Solids covered by Boolean-final runs: 5550
- Final geometry groups: 3508
- Assemblies containing exact repeated-geometry groups: 18
- Exact multi-member groups: 301
- Solids retained in repeated-geometry groups: 2343
- Boolean-checked candidate relations: 55156
- Relations split by the exact layer: 53114
- Splits with completed Boolean-difference evidence: 15170
- Conservative splits still requiring recall review: 37944

## Largest completed Boolean-final assemblies

| Assembly | Solids | Candidate groups | Final groups | Verified differences | Unresolved | Export warning |
|---|---:|---:|---:|---:|---:|---|
| dropbear | 1515 | 263 | 724 | 663 | 2708 | no |
| lambda_cnc | 571 | 51 | 486 | 1989 | 33730 | no |
| hope_glove | 435 | 56 | 165 | 668 | 208 | yes |
| hope_exoskeleton | 393 | 53 | 123 | 334 | 11 | yes |
| rebot_dm_20260425 | 389 | 68 | 350 | 5007 | 340 | no |
| rebot_rs | 370 | 78 | 320 | 3546 | 82 | no |
| renew3d | 339 | 133 | 233 | 198 | 288 | no |
| olsk_cnc | 277 | 97 | 263 | 724 | 406 | no |
| so101 | 266 | 75 | 175 | 1131 | 9 | no |
| knode_robot | 226 | 37 | 76 | 0 | 39 | no |

## Stability and human review

- Input-order/threshold stability runs: 10
- Minimum input-order ARI: 1.0
- Median adjacent-threshold ARI: 1.0
- Independent rigid-transform invariance passed: True
- Risk-stratified human-review items: 166

## Interpretation

`Boolean-final` means that candidate merges were refined using rigid alignment and bidirectional OCCT Boolean difference. An export warning does not erase the classification result: the failed roundtrip manifest and per-group validation remain preserved, and the final report clearly distinguishes classification validity from STEP rewrite fidelity.

Every retained multi-member group is connected by passed precision evidence. `Unresolved` relations are conservatively split after alignment or OCCT failure; they protect merge precision but can reduce recall and are therefore placed in the mandatory human-review queue.

`Rigid-screening` is a full-corpus triage result based on rigid alignment. It is deliberately kept separate from Boolean-final output and must not be interpreted as an exact classification baseline.

The unit is an OCCT Solid, not a functional or manufacturing part name. Multi-solid components can therefore contribute several analysis units.
