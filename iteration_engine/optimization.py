"""Evaluate candidate-clustering thresholds against accepted Boolean-final runs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from geometry_encoder.similarity import density_complete_link

from .io import atomic_write_json, utc_now


def choose2(value: int) -> int:
    return value * (value - 1) // 2


def _load_run(run: Path) -> tuple[list[list[float]], list[str], list[int]]:
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    count = int(report["part_count"])
    matrix = [[0.0] * count for _ in range(count)]
    with (run / "similarities.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            left, right = int(row["part_a"]) - 1, int(row["part_b"]) - 1
            matrix[left][right] = matrix[right][left] = float(row["distance"])
    cache = json.loads((run / "cache_manifest.json").read_text(encoding="utf-8"))
    keys = [row["sha256"] for row in cache["normalized_parts"]
            if str(row.get("file", "")).casefold().endswith(".step")]
    if len(keys) != count:
        raise ValueError(f"{run.name}: expected {count} STEP cache keys, found {len(keys)}")
    final = [0] * count
    for group in report["groups"]:
        for part in group["parts"]:
            final[part - 1] = int(group["group"])
    return matrix, keys, final


def _metrics(candidate: list[int], final: list[int]) -> dict[str, int | float]:
    candidate_sizes = Counter(candidate)
    final_sizes = Counter(final)
    cells = Counter(zip(candidate, final))
    final_same_pairs = sum(choose2(value) for value in final_sizes.values())
    captured_same_pairs = sum(choose2(value) for value in cells.values())
    candidate_pairs = sum(choose2(value) for value in candidate_sizes.values())
    return {
        "candidate_group_count": len(candidate_sizes),
        "candidate_pair_workload": candidate_pairs,
        "boolean_final_same_pairs": final_same_pairs,
        "captured_final_same_pairs": captured_same_pairs,
        "final_pair_recall": captured_same_pairs / final_same_pairs if final_same_pairs else 1.0,
        "candidate_false_pair_workload": candidate_pairs - captured_same_pairs,
    }


def optimize_thresholds(
    runs: Path,
    thresholds: list[float],
    minimum_recall: float,
    output: Path,
    ids: list[str] | None = None,
    baseline_threshold: float = 0.12,
    minimum_workload_reduction: float = 0.01,
) -> dict:
    run_dirs = [path.parent for path in sorted(runs.glob("*/report.json"))]
    if ids:
        selected = set(ids)
        run_dirs = [run for run in run_dirs if run.name in selected]
    aggregate = {threshold: Counter() for threshold in thresholds}
    per_run = []
    for run in run_dirs:
        matrix, keys, final = _load_run(run)
        results = []
        for threshold in thresholds:
            labels = density_complete_link(matrix, threshold, stable_keys=keys)
            metrics = _metrics(labels, final)
            results.append({"threshold": threshold, **metrics})
            for key in ("candidate_pair_workload", "boolean_final_same_pairs",
                        "captured_final_same_pairs", "candidate_false_pair_workload"):
                aggregate[threshold][key] += int(metrics[key])
        per_run.append({"id": run.name, "part_count": len(final), "thresholds": results})
    totals = []
    for threshold in thresholds:
        row = aggregate[threshold]
        denominator = row["boolean_final_same_pairs"]
        recall = row["captured_final_same_pairs"] / denominator if denominator else 1.0
        totals.append({"threshold": threshold, **dict(row), "final_pair_recall": recall})
    eligible = [row for row in totals if row["final_pair_recall"] >= minimum_recall]
    best = min(eligible, key=lambda row: (row["candidate_pair_workload"], row["threshold"]),
               default=None)
    baseline = next((row for row in totals if row["threshold"] == baseline_threshold), None)
    reduction = None
    if best and baseline and baseline["candidate_pair_workload"]:
        reduction = 1 - best["candidate_pair_workload"] / baseline["candidate_pair_workload"]
    recommendation = best if reduction is not None and reduction >= minimum_workload_reduction else None
    result = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "run_count": len(run_dirs),
        "minimum_final_pair_recall": minimum_recall,
        "baseline_threshold": baseline_threshold,
        "minimum_workload_reduction": minimum_workload_reduction,
        "thresholds": totals,
        "recommended_threshold": recommendation["threshold"] if recommendation else None,
        "best_eligible_threshold": best["threshold"] if best else None,
        "best_workload_reduction": reduction,
        "recommendation_status": ("proposal_requires_holdout_validation" if recommendation else
                                  "no_material_gain" if best else "no_eligible_threshold"),
        "per_run": per_run,
    }
    atomic_write_json(output, result)
    return result
