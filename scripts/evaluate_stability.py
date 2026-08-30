#!/usr/bin/env python3
"""Evaluate threshold and input-order stability from completed workflow artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.similarity import density_complete_link


def choose2(value: int) -> int:
    return value * (value - 1) // 2


def adjusted_rand_index(left: list[int], right: list[int]) -> float:
    if len(left) != len(right):
        raise ValueError("Partitions have different lengths")
    n = len(left)
    if n < 2:
        return 1.0
    cells = Counter(zip(left, right))
    left_sizes = Counter(left)
    right_sizes = Counter(right)
    sum_cells = sum(choose2(value) for value in cells.values())
    sum_left = sum(choose2(value) for value in left_sizes.values())
    sum_right = sum(choose2(value) for value in right_sizes.values())
    total = choose2(n)
    expected = sum_left * sum_right / total
    maximum = 0.5 * (sum_left + sum_right)
    denominator = maximum - expected
    if abs(denominator) < 1e-15:
        same = all((left[i] == left[j]) == (right[i] == right[j])
                   for i in range(n) for j in range(i))
        return 1.0 if same else 0.0
    return (sum_cells - expected) / denominator


def load_matrix(run_dir: Path, part_count: int) -> list[list[float]]:
    matrix = [[0.0] * part_count for _ in range(part_count)]
    with (run_dir / "similarities.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            left, right = int(row["part_a"]) - 1, int(row["part_b"]) - 1
            matrix[left][right] = matrix[right][left] = float(row["distance"])
    return matrix


def final_assignments(report: dict) -> list[int]:
    result = [0] * report["part_count"]
    for group in report["groups"]:
        for part in group["parts"]:
            result[part - 1] = group["group"]
    return result


def evaluate_run(run_dir: Path, thresholds: list[float], order_trials: int) -> dict:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    part_count = report["part_count"]
    matrix = load_matrix(run_dir, part_count)
    cache = json.loads((run_dir / "cache_manifest.json").read_text(encoding="utf-8"))
    keys = [row["sha256"] for row in cache["normalized_parts"]
            if str(row.get("file", "")).lower().endswith(".step")]
    if len(keys) != part_count:
        raise ValueError(
            f"{run_dir.name}: expected {part_count} normalized STEP keys, found {len(keys)}"
        )
    partitions = {threshold: density_complete_link(matrix, threshold, stable_keys=keys)
                  for threshold in thresholds}
    rng = random.Random(f"MBD-Pre-order-v2:{run_dir.name}")
    order_aris = {str(threshold): [] for threshold in thresholds}
    for _ in range(order_trials):
        order = list(range(part_count))
        rng.shuffle(order)
        inverse = [0] * part_count
        for position, original in enumerate(order):
            inverse[original] = position
        permuted_matrix = [[matrix[left][right] for right in order] for left in order]
        permuted_keys = [keys[index] for index in order]
        for threshold in thresholds:
            labels = density_complete_link(permuted_matrix, threshold, stable_keys=permuted_keys)
            restored = [labels[inverse[index]] for index in range(part_count)]
            order_aris[str(threshold)].append(adjusted_rand_index(partitions[threshold], restored))
    adjacent = []
    for left, right in zip(thresholds, thresholds[1:]):
        adjacent.append({"left": left, "right": right,
                         "ari": adjusted_rand_index(partitions[left], partitions[right])})
    base_threshold = float(report["config"]["threshold"])
    base_candidate = partitions.get(base_threshold)
    final = final_assignments(report)
    return {
        "id": run_dir.name, "part_count": part_count,
        "thresholds": [{"threshold": threshold, "group_count": len(set(partitions[threshold]))}
                       for threshold in thresholds],
        "adjacent_threshold_ari": adjacent,
        "order_permutation_trials": order_trials,
        "minimum_order_permutation_ari": min(
            (value for values in order_aris.values() for value in values), default=1.0),
        "order_permutation_ari": order_aris,
        "base_candidate_to_final_ari": adjusted_rand_index(base_candidate, final) if base_candidate else None,
        "precision_mode": report["config"]["precision_mode"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "runs" / "assembly_corpus")
    parser.add_argument("--output", type=Path, default=ROOT / "research" / "stability_report.json")
    parser.add_argument("--thresholds", nargs="*", type=float, default=[0.08, 0.10, 0.12, 0.14, 0.16])
    parser.add_argument("--order-trials", type=int, default=10)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--max-parts", type=int)
    parser.add_argument("--include-nonboolean", action="store_true")
    args = parser.parse_args()
    runs = [path.parent for path in sorted(args.runs.glob("*/report.json"))]
    if args.ids:
        selected = set(args.ids)
        runs = [run for run in runs if run.name in selected]
    if not args.include_nonboolean:
        runs = [run for run in runs if json.loads((run / "report.json").read_text(encoding="utf-8"))
                .get("config", {}).get("precision_mode") == "boolean"]
    if args.max_parts is not None:
        runs = [run for run in runs if json.loads((run / "report.json").read_text(encoding="utf-8"))
                .get("part_count", 0) <= args.max_parts]
    if args.order_trials < 1:
        parser.error("--order-trials must be at least 1")
    results = [evaluate_run(run, args.thresholds, args.order_trials) for run in runs]
    adjacent_values = [item["ari"] for result in results for item in result["adjacent_threshold_ari"]]
    refinement_values = [result["base_candidate_to_final_ari"] for result in results
                         if result["base_candidate_to_final_ari"] is not None]
    summary = {
        "schema_version": 1, "run_count": len(results), "runs": results,
        "all_input_order_invariant": all(result["minimum_order_permutation_ari"] == 1.0 for result in results),
        "minimum_order_permutation_ari": min((result["minimum_order_permutation_ari"] for result in results), default=None),
        "median_adjacent_threshold_ari": (sorted(adjacent_values)[len(adjacent_values) // 2]
                                          if adjacent_values else None),
        "median_candidate_to_boolean_final_ari": (
            sorted(refinement_values)[len(refinement_values) // 2] if refinement_values else None
        ),
        "minimum_candidate_to_boolean_final_ari": min(refinement_values, default=None),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, ensure_ascii=False))
    return 0 if results and summary["all_input_order_invariant"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
