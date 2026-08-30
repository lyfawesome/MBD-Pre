# Source selection audit

## Admission policy

Admit openly downloadable STEP assemblies with an explicit reusable license and at least 10 OCCT Solid entities. Prefer complete mechanisms with repeated hardware or repeated structural parts. Preserve every failure and exclusion instead of silently dropping it.

## Current inventory

- Core candidates: 29
- Quarantined candidates: 1
- Downloaded or verified: 29
- Structurally admitted: 28
- Classified: 22

## Explicit exclusions and deferrals

- `xt1`: quarantined because the repository license could not be established.
- AutoMate: qualified_not_bulk_downloaded; The monolithic STEP archive is 13.2 GB; retained as an expansion source after the 29-file core is validated.
- Quidities open-source assembly gallery: discovery_only; Used to discover and cross-check assembly sizes; original STEP files are downloaded from upstream repositories.

## Known limitations

GitHub-hosted assemblies are heterogeneous and do not provide authoritative pair labels. Therefore geometric precision evidence is combined with a risk-stratified human queue. The corpus measures geometric grouping, not functional part-name classification.
