# Assembly corpus workspace

This directory turns the external-assembly experiment into a reproducible workflow. Generated CSV files are local audit artifacts and are excluded from Git because they contain machine-specific paths; the source manifest, scripts, protocol and selection audit remain versionable.

## Reproduce

From the repository root:

```bash
python3 scripts/acquire_assembly_data.py --workers 16 --retries 5
python3 scripts/inspect_step_assemblies.py --workers 2 --minimum-solids 10
python3 scripts/run_assembly_corpus.py --precision-mode boolean --precision-workers 8 --skip-step-export
python3 scripts/evaluate_stability.py --order-trials 10
python3 scripts/evaluate_rigid_invariance.py
python3 scripts/build_human_review.py
python3 scripts/build_research_audit.py
python3 scripts/summarize_corpus.py
```

The downloader resumes `.part` files and verifies size, STEP header and SHA-256. The inspection stage rejects isolated or undersized models. The normalizer imports each source once and writes both reviewable per-part STEP and exact OCCT-native B-Rep caches. Boolean checks load the two small native shapes, process four candidate pairs per batch, and recursively split a failed batch until only the pathological pair is isolated. Each finished leaf batch is atomically checkpointed. Checkpoint schema 2 records the precision-algorithm revision; migration from schema 1 keeps completed `verified`/`different` Boolean evidence but deliberately re-evaluates unresolved alignment or Boolean failures. `--skip-step-export` keeps all classification and per-part review artifacts while avoiding a redundant grouped-STEP rewrite for the large corpus. Omit it when grouped STEP deliverables are required; an export failure is then preserved separately from a successful classification.

The review renderer needs the optional dependencies declared in `pyproject.toml`; install them with `pip install -e '.[review]'`. All commands and manifests use repository-relative defaults. Downloaded models, run directories and machine-specific reports are deliberately ignored by Git and can be regenerated from `assembly_sources.json`.

## Final versus screening results

Only `precision_mode=boolean` is an accepted final result. `rigid` outputs are screening results used to estimate cost and identify cases that need exact review. The SO-100 comparison demonstrated that a rigid result can materially over-merge geometrically close parts.

## Human review

Open `human_review/index.html`. Each row shows canonical PCA-aligned isometric, front and top views for a high-risk group, a high-similarity cross-group pair, a precision split, or a random baseline item. The individual normalized STEP files remain one click away for uncertain images. Choices and notes are saved in browser local storage, so a review can be resumed after closing the page. The similarity table is sampled in one streaming pass with bounded memory, including for the 1,515-solid Dropbear model. Select a label and click **导出标注 CSV**. Score the downloaded file with:

```bash
python3 scripts/score_human_review.py /path/to/human_labels.csv
```

The review is about geometric equivalence, not functional names such as “screw” or “nut”. A STEP `Solid` is the unit used by the current algorithm; multi-solid manufacturing parts may therefore be split into several analysis units.
