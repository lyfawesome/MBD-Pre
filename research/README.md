# Assembly corpus workspace

This directory turns the external-assembly experiment into a reproducible workflow. Generated CSV files are local audit artifacts and are excluded from Git because they contain machine-specific paths; the source manifest, scripts, protocol and selection audit remain versionable.

The remote-source layer also keeps a versioned non-Git channel catalog and metadata-first candidate set. Run `python3 scripts/prescreen_sources.py --reuse-probes` to rebuild sector, engineering-domain, likely-component and assembly-confidence statistics without downloading any complete CAD model. Use `--probe` only when bounded HTTP range reads are desired.

## Reproduce

From the repository root:

```bash
conda env create -f environment.yml
conda activate mbd-pre
./scripts/run_reproduce.sh full
```

The individual commands remain visible in `scripts/run_reproduce.sh`. Worker counts can be overridden with `MBD_DOWNLOAD_WORKERS`, `MBD_INSPECTION_WORKERS` and `MBD_PRECISION_WORKERS`.

Every core source in `assembly_sources.json` is locked by an immutable Git commit, byte count and SHA-256; all 29 core URLs were rechecked successfully. The quarantined `xt1` lead remains unavailable and license-unknown, so it is never acquired automatically. The downloader uses the immutable commit rather than the descriptive branch name, resumes `.part` files and verifies size, STEP header and SHA-256. The inspection stage rejects isolated or undersized models. The normalizer imports each source once and writes both reviewable per-part STEP and exact OCCT-native B-Rep caches. Boolean checks load the two small native shapes and process four candidate pairs per batch. If a batch fails or times out, its pairs are retried independently as singletons in the shared worker pool, so pathological B-Reps cannot serialize unrelated fallback checks. Each finished batch or singleton is atomically checkpointed. Checkpoint schema 2 records the precision-algorithm revision; migration from schema 1 keeps completed `verified`/`different` Boolean evidence but deliberately re-evaluates unresolved alignment or Boolean failures. `--skip-step-export` keeps all classification and per-part review artifacts while avoiding a redundant grouped-STEP rewrite for the large corpus. Omit it when grouped STEP deliverables are required; an export failure is then preserved separately from a successful classification.

The review renderer needs the optional dependencies declared in `pyproject.toml`; install them with `pip install -e '.[review]'`. All commands and manifests use repository-relative defaults. Downloaded models, run directories and machine-specific reports are deliberately ignored by Git and can be regenerated from `assembly_sources.json`.

## Final versus screening results

Only `precision_mode=boolean` is an accepted final result. `rigid` outputs are screening results used to estimate cost and identify cases that need exact review. The SO-100 comparison demonstrated that a rigid result can materially over-merge geometrically close parts.

The conditional 29-assembly benchmark requested for the WeChat 2026-09 package is recorded in [FAST_VS_FULL_RIGID_2026_09.md](FAST_VS_FULL_RIGID_2026_09.md). It compares fast clustering with global rigid-only representative grouping, excludes STEP normalization from timing, and documents the important fewer-than-three-vertices limitation before treating rigid as ground truth.

## Human review

Open `human_review/index.html`. Each row shows canonical PCA-aligned isometric, front and top views for a high-risk group, a high-similarity cross-group pair, a precision split, or a random baseline item. The individual normalized STEP files remain one click away for uncertain images. Choices and notes are saved in browser local storage, so a review can be resumed after closing the page. The similarity table is sampled in one streaming pass with bounded memory, including for the 1,515-solid Dropbear model. Select a label and click **导出标注 CSV**. Score the downloaded file with:

```bash
python3 scripts/score_human_review.py /path/to/human_labels.csv
```

The review is about geometric equivalence, not functional names such as “screw” or “nut”. A STEP `Solid` is the unit used by the current algorithm; multi-solid manufacturing parts may therefore be split into several analysis units.
