# Current corpus status

Snapshot: 2026-08-31 (Asia/Shanghai)

## Completed Boolean-final coverage

- Downloaded and SHA-256 verified STEP assemblies: 29
- Structurally admitted assemblies: 28
- Completed Boolean-final assemblies: 25
- Solids classified: 6,562
- Final geometry groups: 4,161
- Assemblies containing repeated geometry: 21
- Exact multi-member groups: 366
- Solids in repeated groups: 2,767
- Candidate relations checked: 59,728
- Relations split by the exact layer: 57,327
- Splits supported by completed Boolean-difference evidence: 19,083
- Conservative unresolved splits: 38,244

The aggregate metrics above are rebuilt from completed per-run `report.json` and
`precision_report.json` artifacts. They measure geometric-equivalence grouping,
not functional labels such as screw, nut or valve, and they are not a substitute
for a fully human-labelled accuracy benchmark.

## Paused and pending work

- `voron_legacy`: paused after 921 precision relations; its local checkpoint is
  intentionally excluded from Git and can be resumed after reacquiring the locked source.
- `hros1_orion`: admitted, Boolean-final run not started.
- `neoracer`: admitted, Boolean-final run not started.

Raw STEP files, normalized parts, precision checkpoints and review renderings are
not versioned. The immutable source commits, byte counts and SHA-256 values in
`assembly_sources.json` are the canonical inputs for rebuilding them.
