"""Run an explicit Boolean-final holdout benchmark for a parameter proposal."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .io import atomic_write_json, utc_now


def _rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def _assignments(path: Path) -> list[int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    labels = [0] * int(report["part_count"])
    for group in report["groups"]:
        for part in group["parts"]:
            labels[part - 1] = int(group["group"])
    return labels


def _choose2(value: int) -> int:
    return value * (value - 1) // 2


def adjusted_rand_index(left: list[int], right: list[int]) -> float:
    if len(left) != len(right):
        raise ValueError("Partitions have different lengths")
    if len(left) < 2:
        return 1.0
    cells, left_sizes, right_sizes = Counter(zip(left, right)), Counter(left), Counter(right)
    same = sum(_choose2(value) for value in cells.values())
    left_pairs = sum(_choose2(value) for value in left_sizes.values())
    right_pairs = sum(_choose2(value) for value in right_sizes.values())
    total = _choose2(len(left))
    expected = left_pairs * right_pairs / total
    maximum = (left_pairs + right_pairs) / 2
    return (same - expected) / (maximum - expected) if maximum != expected else 1.0


def run_holdout_benchmark(
    root: Path,
    ids: list[str],
    threshold: float,
    workers: int,
    output: Path,
) -> dict:
    benchmark_root = root / "runs" / "algorithm_benchmark" / f"threshold_{threshold:g}"
    benchmark_index = root / "research" / "benchmark" / f"threshold_{threshold:g}_runs.csv"
    command = [
        sys.executable, "scripts/run_assembly_corpus.py", "--ids", *ids,
        "--runs", str(benchmark_root), "--index", str(benchmark_index),
        "--threshold", str(threshold), "--precision-mode", "boolean",
        "--precision-workers", str(workers), "--skip-step-export",
    ]
    completed = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    if completed.returncode:
        result = {"schema_version": 1, "generated_at": utc_now(), "status": "failed",
                  "threshold": threshold, "ids": ids, "output_tail": completed.stdout[-4000:]}
        atomic_write_json(output, result)
        return result

    baseline_rows = _rows(root / "research" / "classification_runs.csv")
    candidate_rows = _rows(benchmark_index)
    runs = []
    for source_id in ids:
        baseline = baseline_rows[source_id]
        candidate = candidate_rows[source_id]
        baseline_labels = _assignments(root / "runs" / "assembly_corpus" / source_id / "report.json")
        candidate_labels = _assignments(benchmark_root / source_id / "report.json")
        baseline_elapsed = float(baseline["elapsed_seconds"])
        candidate_elapsed = float(candidate["elapsed_seconds"])
        runs.append({
            "id": source_id,
            "adjusted_rand_index": adjusted_rand_index(baseline_labels, candidate_labels),
            "baseline_elapsed_seconds": baseline_elapsed,
            "candidate_elapsed_seconds": candidate_elapsed,
            "runtime_ratio": candidate_elapsed / baseline_elapsed if baseline_elapsed > 0 else None,
        })
    baseline_total = sum(row["baseline_elapsed_seconds"] for row in runs)
    candidate_total = sum(row["candidate_elapsed_seconds"] for row in runs)
    result = {
        "schema_version": 1, "generated_at": utc_now(), "status": "completed",
        "threshold": threshold, "ids": ids,
        "minimum_partition_ari": min(row["adjusted_rand_index"] for row in runs),
        "runtime_ratio": candidate_total / baseline_total if baseline_total > 0 else None,
        "runs": runs,
    }
    atomic_write_json(output, result)
    return result
