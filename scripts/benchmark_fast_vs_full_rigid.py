#!/usr/bin/env python3
"""Benchmark fast clustering against full rigid-only representative grouping."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.precision import RigidGeometry, find_rigid_transform, load_rigid_geometry
from iteration_engine.benchmark import adjusted_rand_index


def pair_metrics(predicted: list[int], truth: list[int]) -> dict[str, float | int]:
    if len(predicted) != len(truth):
        raise ValueError("assignment lengths differ")
    true_positive = false_positive = false_negative = true_negative = 0
    for right in range(len(truth)):
        for left in range(right):
            predicted_same = predicted[left] == predicted[right]
            truth_same = truth[left] == truth[right]
            if predicted_same and truth_same:
                true_positive += 1
            elif predicted_same:
                false_positive += 1
            elif truth_same:
                false_negative += 1
            else:
                true_negative += 1
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = ((true_positive + true_negative) /
                max(1, true_positive + false_positive + false_negative + true_negative))
    return {
        "true_positive_pairs": true_positive,
        "false_positive_pairs": false_positive,
        "false_negative_pairs": false_negative,
        "true_negative_pairs": true_negative,
        "pair_precision": precision,
        "pair_recall": recall,
        "pair_f1": f1,
        "pair_accuracy": accuracy,
        "adjusted_rand_index": adjusted_rand_index(predicted, truth),
    }


def rigid_invariant_key(geometry: RigidGeometry) -> tuple:
    """Return only necessary rigid invariants, never the fast descriptor."""
    curve_types = Counter()
    for (_, _, curve), count in geometry.edges.items():
        curve_types[curve] += count
    surface_types = Counter()
    for (surface, _), count in geometry.faces.items():
        surface_types[surface] += count
    return (
        len(geometry.points), sum(geometry.edges.values()), sum(geometry.faces.values()),
        tuple(sorted(curve_types.items())), tuple(sorted(surface_types.items())),
    )


def full_rigid_group(
    geometries: list[RigidGeometry], tolerance: float,
) -> tuple[list[int], int, int]:
    """Group globally using rigid checks against every compatible representative."""
    roots_by_key: dict[tuple, list[tuple[int, int]]] = {}
    assignments: list[int] = []
    comparisons = skipped_by_invariant = group_count = roots_seen = 0
    for candidate_index, candidate in enumerate(geometries):
        key = rigid_invariant_key(candidate)
        compatible_roots = roots_by_key.setdefault(key, [])
        skipped_by_invariant += roots_seen - len(compatible_roots)
        assigned_group = None
        for reference_index, group_id in compatible_roots:
            comparisons += 1
            reference = geometries[reference_index]
            transform = find_rigid_transform(
                reference.points, candidate.points, tolerance,
                reference.edges, candidate.edges, reference.faces, candidate.faces,
            )
            if transform is not None:
                assigned_group = group_id
                break
        if assigned_group is None:
            group_count += 1
            assigned_group = group_count
            compatible_roots.append((candidate_index, assigned_group))
            roots_seen += 1
        assignments.append(assigned_group)
    return assignments, comparisons, skipped_by_invariant


def stage_seconds(manifest: dict, name: str) -> float:
    for stage in manifest.get("stages", []):
        if stage.get("name") == name:
            return float(stage.get("duration_seconds", 0.0))
    return 0.0


def assignments_from_report(report: dict) -> list[int]:
    ordered = sorted(report["parts"], key=lambda row: int(row["part_index"]))
    return [int(part["group"]) for part in ordered]


def run_fast(source: Path, output: Path, threshold: float) -> tuple[dict, dict]:
    command = [
        sys.executable, str(ROOT / "step_geometry_encoder.py"), str(source),
        "--output", str(output), "--precision-mode", "off",
        "--threshold", str(threshold), "--skip-step-export", "--allow-unknown-geometry",
    ]
    if (output / "cache_manifest.json").is_file():
        command.append("--reuse-cache")
    completed = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    (output / "benchmark_fast_console.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(completed.stdout[-4000:])
    return (
        json.loads((output / "report.json").read_text(encoding="utf-8")),
        json.loads((output / "workflow_manifest.json").read_text(encoding="utf-8")),
    )


def benchmark_one(source: Path, output: Path, threshold: float, tolerance: float) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    fast_report, manifest = run_fast(source, output, threshold)
    part_count = int(fast_report["part_count"])
    normalized = output / "normalized_parts"

    started = time.perf_counter()
    geometries = [load_rigid_geometry(normalized / f"part_{index:04d}.step")
                  for index in range(1, part_count + 1)]
    rigid_representation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    rigid_assignments, rigid_comparisons, skipped = full_rigid_group(geometries, tolerance)
    rigid_grouping_seconds = time.perf_counter() - started
    fast_assignments = assignments_from_report(fast_report)

    normalize_seconds = stage_seconds(manifest, "normalize")
    fast_feature_seconds = stage_seconds(manifest, "feature_collection")
    fast_similarity_seconds = stage_seconds(manifest, "similarity")
    fast_clustering_seconds = stage_seconds(manifest, "candidate_clustering")
    fast_core_seconds = fast_similarity_seconds + fast_clustering_seconds
    fast_algorithm_seconds = fast_feature_seconds + fast_core_seconds
    rigid_algorithm_seconds = rigid_representation_seconds + rigid_grouping_seconds
    result = {
        "source": str(source.resolve()), "part_count": part_count,
        "fast_group_count": len(set(fast_assignments)),
        "rigid_group_count": len(set(rigid_assignments)),
        "threshold": threshold, "vertex_tolerance": tolerance,
        "normalization_seconds_excluded": normalize_seconds,
        "fast_feature_seconds": fast_feature_seconds,
        "fast_similarity_seconds": fast_similarity_seconds,
        "fast_clustering_seconds": fast_clustering_seconds,
        "fast_core_grouping_seconds": fast_core_seconds,
        "fast_algorithm_seconds_excluding_normalization": fast_algorithm_seconds,
        "rigid_representation_seconds": rigid_representation_seconds,
        "rigid_core_grouping_seconds": rigid_grouping_seconds,
        "rigid_algorithm_seconds_excluding_normalization": rigid_algorithm_seconds,
        "rigid_to_fast_core_ratio": rigid_grouping_seconds / max(fast_core_seconds, 1e-12),
        "rigid_to_fast_algorithm_ratio": rigid_algorithm_seconds / max(fast_algorithm_seconds, 1e-12),
        "rigid_transform_comparisons": rigid_comparisons,
        "root_comparisons_skipped_by_exact_invariants": skipped,
        **pair_metrics(fast_assignments, rigid_assignments),
        "fast_assignments": fast_assignments, "rigid_assignments": rigid_assignments,
    }
    (output / "fast_vs_full_rigid.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def write_summary(rows: list[dict], path: Path) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "fast_vs_full_rigid")
    parser.add_argument("--threshold", type=float, default=0.12)
    parser.add_argument("--vertex-tolerance", type=float, default=1e-5)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    sources = sorted(
        (path for path in args.source_dir.iterdir()
         if path.is_file() and path.suffix.lower() in {".step", ".stp"}),
        key=lambda path: (path.stat().st_size, path.name),
    )
    if args.ids:
        selected = set(args.ids)
        sources = [path for path in sources if path.stem in selected or path.name in selected]
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for position, source in enumerate(sources, 1):
        print(f"[{position}/{len(sources)}] {source.name}", flush=True)
        result_path = args.output / source.stem / "fast_vs_full_rigid.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            print(f"  reused parts={result['part_count']}", flush=True)
        else:
            try:
                result = benchmark_one(source, args.output / source.stem,
                                       args.threshold, args.vertex_tolerance)
            except Exception as error:
                result = {"source": str(source.resolve()),
                          "error": f"{type(error).__name__}: {error}"}
                (args.output / f"{source.stem}_error.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"  FAILED {result['error']}", flush=True)
                continue
            print(
                f"  parts={result['part_count']} groups={result['fast_group_count']}/"
                f"{result['rigid_group_count']} F1={result['pair_f1']:.6f} "
                f"time={result['fast_algorithm_seconds_excluding_normalization']:.3f}/"
                f"{result['rigid_algorithm_seconds_excluding_normalization']:.3f}s",
                flush=True,
            )
        rows.append({key: value for key, value in result.items() if not isinstance(value, list)})
        write_summary(rows, args.output / "summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
