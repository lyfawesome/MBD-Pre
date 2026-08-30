"""Evidence-based promotion gates for an algorithm iteration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import atomic_write_json, load_json, utc_now


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_gates(research: Path, gates: dict[str, Any], output: Path) -> dict:
    summary = load_json(research / "final_summary.json", {})
    human = load_json(research / "human_review" / "human_accuracy_report.json", {})
    benchmark = load_json(research / "benchmark" / "candidate_evaluation.json", {})
    checks = []

    def add(name: str, passed: bool | None, observed: Any, required: Any, blocking: bool = True) -> None:
        checks.append({"name": name, "passed": passed, "observed": observed,
                       "required": required, "blocking": blocking})

    stability = summary.get("stability", {})
    add("input_order_ari", (_number(stability.get("minimum_order_permutation_ari")) or 0)
        >= float(gates["minimum_order_ari"]), stability.get("minimum_order_permutation_ari"),
        gates["minimum_order_ari"])
    add("threshold_ari", (_number(stability.get("median_adjacent_threshold_ari")) or 0)
        >= float(gates["minimum_threshold_ari"]), stability.get("median_adjacent_threshold_ari"),
        gates["minimum_threshold_ari"])
    rigid = summary.get("rigid_invariance", {})
    add("rigid_invariance", rigid.get("all_passed") is True, rigid.get("all_passed"), True)
    add("minimum_completed_assemblies", int(summary.get("boolean_completed_assemblies", 0))
        >= int(gates["minimum_completed_assemblies"]), summary.get("boolean_completed_assemblies", 0),
        gates["minimum_completed_assemblies"])
    benchmark_ari = _number(benchmark.get("minimum_partition_ari"))
    runtime_ratio = _number(benchmark.get("runtime_ratio"))
    add("holdout_partition_ari", None if benchmark_ari is None else
        benchmark_ari >= float(gates["minimum_holdout_partition_ari"]), benchmark_ari,
        gates["minimum_holdout_partition_ari"])
    add("holdout_runtime_ratio", None if runtime_ratio is None else
        runtime_ratio <= float(gates["maximum_holdout_runtime_ratio"]), runtime_ratio,
        gates["maximum_holdout_runtime_ratio"])

    precision = _number(human.get("merge_precision", {}).get("estimate"))
    precision_low = _number(human.get("merge_precision", {}).get("wilson_low"))
    split = _number(human.get("random_cross_correct_split", {}).get("estimate"))
    split_low = _number(human.get("random_cross_correct_split", {}).get("wilson_low"))
    add("human_merge_precision", None if precision is None else precision >= float(gates["minimum_merge_precision"]),
        precision, gates["minimum_merge_precision"])
    add("human_merge_precision_lower_bound", None if precision_low is None else
        precision_low >= float(gates["minimum_merge_precision_lower_bound"]), precision_low,
        gates["minimum_merge_precision_lower_bound"])
    add("random_cross_correct_split", None if split is None else
        split >= float(gates["minimum_random_cross_correct_split"]), split,
        gates["minimum_random_cross_correct_split"])
    add("random_cross_lower_bound", None if split_low is None else
        split_low >= float(gates["minimum_random_cross_lower_bound"]), split_low,
        gates["minimum_random_cross_lower_bound"])

    failed = [check for check in checks if check["blocking"] and check["passed"] is False]
    missing = [check for check in checks if check["blocking"] and check["passed"] is None]
    decision = "rejected" if failed else "waiting_for_human_labels" if missing else "eligible_for_promotion"
    result = {"schema_version": 1, "generated_at": utc_now(), "decision": decision,
              "checks": checks, "failed_checks": [row["name"] for row in failed],
              "missing_checks": [row["name"] for row in missing]}
    atomic_write_json(output, result)
    return result
