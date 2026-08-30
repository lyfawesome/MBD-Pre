"""Command-line entry point for continuous corpus and algorithm iteration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, ROOT, load_config
from .benchmark import run_holdout_benchmark
from .coverage import build_coverage
from .discovery import discover
from .gates import evaluate_gates
from .io import atomic_write_json, load_json, utc_now
from .optimization import optimize_thresholds
from .state import CycleState


RESEARCH = ROOT / "research"
DISCOVERY = RESEARCH / "discovery"


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _coverage(config) -> dict:
    return build_coverage(
        [ROOT / "data" / "assemblies", ROOT / "data" / "discovered"],
        [ROOT / "runs" / "assembly_corpus", ROOT / "runs" / "discovered"], config.taxonomy,
        RESEARCH / "coverage_report.json",
        int(config.raw["coverage"]["minimum_sources_per_type"]),
    )


def _discovery(config, coverage: dict) -> dict:
    settings = config.discovery
    missing = coverage["coverage_gaps"][:int(settings["max_missing_types_per_cycle"])]
    return discover(
        missing, config.taxonomy, settings["providers"],
        int(settings["results_per_query"]), settings["allowed_licenses"],
        int(settings["maximum_file_bytes"]), DISCOVERY / "candidates.json",
        DISCOVERY / "acquisition_attempts.json", float(settings["query_deadline_seconds"]),
    )


def _write_discovered_manifest(candidates: dict, maximum_sources: int) -> dict:
    sources = []
    for candidate in candidates.get("candidates", []):
        if candidate.get("decision") != "staged" or not candidate.get("download_url"):
            continue
        sources.append({
            "id": candidate["candidate_id"], "title": candidate["title"],
            "download_url": candidate["download_url"], "filename": candidate["filename"],
            "license": candidate["license"], "expected_bytes": candidate.get("expected_bytes"),
            "tier": "discovered", "entity_type": candidate["matched_type"],
            "landing_url": candidate["landing_url"],
        })
    sources = sources[:maximum_sources]
    manifest = {
        "schema_version": 1, "generated_at": utc_now(),
        "selection_policy": "Machine-staged candidates; structural admission remains mandatory.",
        "sources": sources,
    }
    atomic_write_json(DISCOVERY / "staged_sources.json", manifest)
    return manifest


def command_plan(args) -> int:
    config = load_config(args.config)
    result = {
        "config": str(config.path),
        "stages": [
            "coverage: extract STEP PRODUCT-name and geometry-signature gaps",
            "discover: query configured providers only for missing semantic types",
            "stage: enforce license, extension and file-size policy",
            "acquire/inspect: hash raw files and require valid multi-solid STEP",
            "classify: candidate clustering followed by independent Boolean verification",
            "optimize: minimize candidate-pair workload subject to final-pair recall",
            "evaluate: order/threshold/rigid/human evidence promotion gates",
            "review: promote only after required human labels are present",
        ],
        "safety": {
            "raw_models_tracked_by_git": False,
            "unknown_license_auto_admission": False,
            "automatic_algorithm_promotion": False,
        },
    }
    _print(result)
    return 0


def command_coverage(args) -> int:
    result = _coverage(load_config(args.config))
    _print({key: value for key, value in result.items() if key != "geometry_signatures"})
    return 0


def command_discover(args) -> int:
    config = load_config(args.config)
    coverage = _coverage(config)
    result = _discovery(config, coverage)
    manifest = _write_discovered_manifest(result, int(config.cycle["maximum_new_sources"]))
    _print({"coverage_gaps": coverage["coverage_gaps"],
            "candidate_count": len(result["candidates"]),
            "staged_count": len(manifest["sources"]),
            "successful_queries": result["successful_queries"],
            "failed_queries": result["failed_queries"]})
    return 0 if not result["query_count"] or result["successful_queries"] else 1


def command_optimize(args) -> int:
    config = load_config(args.config)
    result = optimize_thresholds(
        ROOT / "runs" / "assembly_corpus", config.thresholds,
        float(config.raw["optimization"]["minimum_final_pair_recall"]),
        RESEARCH / "optimization" / "candidate_threshold_report.json", args.ids,
        float(config.raw["optimization"]["baseline_threshold"]),
        float(config.raw["optimization"]["minimum_workload_reduction"]),
    )
    _print({key: value for key, value in result.items() if key != "per_run"})
    return 0 if result["run_count"] else 1


def command_evaluate(args) -> int:
    result = evaluate_gates(RESEARCH, load_config(args.config).gates,
                            RESEARCH / "promotion_decision.json")
    _print(result)
    return 0 if result["decision"] != "rejected" else 1


def command_benchmark(args) -> int:
    config = load_config(args.config)
    threshold = args.threshold
    if threshold is None:
        optimization = load_json(RESEARCH / "optimization" / "candidate_threshold_report.json", {})
        threshold = optimization.get("recommended_threshold")
    if threshold is None:
        raise SystemExit("No candidate threshold supplied and no optimization recommendation exists")
    result = run_holdout_benchmark(
        ROOT, list(config.raw["optimization"]["holdout_ids"]), float(threshold),
        int(config.cycle["precision_workers"]),
        RESEARCH / "benchmark" / "candidate_evaluation.json",
    )
    _print(result)
    return 0 if result["status"] == "completed" else 1


def command_cycle(args) -> int:
    config = load_config(args.config)
    state_path = RESEARCH / "iterations" / "latest_cycle.json"
    state = CycleState(state_path, config.path)
    coverage = _coverage(config)
    state.record_internal_stage("coverage", {
        "coverage_gaps": coverage["coverage_gaps"],
        "geometry_signatures": coverage["classified_geometry_signatures"],
    })
    candidates = None
    if not args.offline:
        candidates = _discovery(config, coverage)
        state.record_internal_stage("discover", {"candidate_count": len(candidates["candidates"])})
        if candidates["query_count"] and not candidates["successful_queries"]:
            state.finish("failed")
            _print({"error": "all_discovery_queries_failed",
                    "audit": str(DISCOVERY / "acquisition_attempts.json")})
            return 1
        manifest = _write_discovered_manifest(candidates, int(config.cycle["maximum_new_sources"]))
        python = sys.executable
        if args.acquire and manifest["sources"]:
            commands = [
                ("acquire", [python, "scripts/acquire_assembly_data.py", "--manifest",
                             str(DISCOVERY / "staged_sources.json"), "--output",
                             str(ROOT / "data" / "discovered"), "--log",
                             str(DISCOVERY / "acquisition_log.csv"), "--inventory",
                             str(DISCOVERY / "raw_file_inventory.csv")]),
                ("inspect", [python, "scripts/inspect_step_assemblies.py", "--manifest",
                             str(DISCOVERY / "staged_sources.json"), "--input",
                             str(ROOT / "data" / "discovered"), "--output",
                             str(DISCOVERY / "inspection_results.csv")]),
            ]
            for name, command in commands:
                if state.record_python_stage(name, command, ROOT):
                    return 1
        if args.classify:
            inspection = DISCOVERY / "inspection_results.csv"
            if not inspection.is_file():
                state.finish("failed")
                _print({"error": "classification_requires_inspection_results",
                        "expected": str(inspection)})
                return 1
            command = [python, "scripts/run_assembly_corpus.py", "--inspection",
                       str(inspection), "--runs", str(ROOT / "runs" / "discovered"),
                       "--index", str(DISCOVERY / "classification_runs.csv"),
                       "--precision-mode", "boolean", "--skip-step-export",
                       "--precision-workers", str(config.cycle["precision_workers"])]
            if state.record_python_stage("classify", command, ROOT):
                return 1
    optimization = optimize_thresholds(
        ROOT / "runs" / "assembly_corpus", config.thresholds,
        float(config.raw["optimization"]["minimum_final_pair_recall"]),
        RESEARCH / "optimization" / "candidate_threshold_report.json",
        baseline_threshold=float(config.raw["optimization"]["baseline_threshold"]),
        minimum_workload_reduction=float(config.raw["optimization"]["minimum_workload_reduction"]),
    )
    state.record_internal_stage("optimize", {
        "status": optimization["recommendation_status"],
        "recommended_threshold": optimization["recommended_threshold"],
    })
    decision = evaluate_gates(RESEARCH, config.gates, RESEARCH / "promotion_decision.json")
    state.record_internal_stage("evaluate", {"decision": decision["decision"]})
    state.value["outputs"] = {
        "coverage_report": str(RESEARCH / "coverage_report.json"),
        "discovery_candidates": str(DISCOVERY / "candidates.json") if candidates else None,
        "recommended_threshold": optimization["recommended_threshold"],
        "promotion_decision": decision["decision"],
    }
    state.finish()
    _print(state.value["outputs"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan").set_defaults(function=command_plan)
    subparsers.add_parser("coverage").set_defaults(function=command_coverage)
    subparsers.add_parser("discover").set_defaults(function=command_discover)
    optimize = subparsers.add_parser("optimize")
    optimize.add_argument("--ids", nargs="*")
    optimize.set_defaults(function=command_optimize)
    subparsers.add_parser("evaluate").set_defaults(function=command_evaluate)
    benchmark = subparsers.add_parser("benchmark")
    benchmark.add_argument("--threshold", type=float)
    benchmark.set_defaults(function=command_benchmark)
    cycle = subparsers.add_parser("cycle")
    cycle.add_argument("--offline", action="store_true", help="Skip internet discovery")
    cycle.add_argument("--acquire", action="store_true", help="Download machine-staged candidates")
    cycle.add_argument("--classify", action="store_true", help="Classify admitted downloaded candidates")
    cycle.set_defaults(function=command_cycle)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.function(args)


if __name__ == "__main__":
    raise SystemExit(main())
