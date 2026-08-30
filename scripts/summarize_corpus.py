#!/usr/bin/env python3
"""Create the final machine-readable and Markdown corpus summary."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"


def csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "runs" / "assembly_corpus",
                        help="Directory containing Boolean-final runs")
    parser.add_argument("--screening-runs", type=Path, default=ROOT / "runs" / "rigid_corpus",
                        help="Directory containing rigid-screening runs")
    parser.add_argument("--output", type=Path, default=RESEARCH / "final_summary.json")
    args = parser.parse_args()
    inventory = csv_rows(RESEARCH / "raw_data_file_inventory.csv")
    inspection = csv_rows(RESEARCH / "inspection_results.csv")
    inspected = {row["id"]: row for row in inspection}
    run_rows = []
    report_paths = [(path, "boolean_final") for path in sorted(args.runs.glob("*/report.json"))]
    report_paths += [(path, "rigid_screening")
                     for path in sorted(args.screening_runs.glob("*/report.json"))]
    for report_path, tier in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        run_dir = report_path.parent
        precision_path = run_dir / "precision_report.json"
        precision = json.loads(precision_path.read_text(encoding="utf-8")) if precision_path.is_file() else {}
        precision_pairs = precision.get("pairs", [])
        workflow = json.loads((run_dir / "workflow_manifest.json").read_text(encoding="utf-8"))
        groups = report["groups"]
        group_manifest_path = run_dir / "grouped_steps" / "manifest.json"
        max_export_error = None
        export_valid = None
        if group_manifest_path.is_file():
            validations = json.loads(group_manifest_path.read_text(encoding="utf-8"))["validation"]
            max_export_error = max((row["volume_relative_error"] for row in validations), default=0.0)
            export_valid = all(row["valid"] for row in validations)
        run_rows.append({
            "id": run_dir.name, "coverage_tier": tier, "workflow_status": workflow["status"],
            "precision_mode": report["config"]["precision_mode"], "solid_count": report["part_count"],
            "candidate_groups": report["candidate_group_count"], "final_groups": report["group_count"],
            "multi_member_groups": sum(group["part_count"] > 1 for group in groups),
            "solids_in_multi_member_groups": sum(group["part_count"] for group in groups if group["part_count"] > 1),
            "checked_pairs": precision.get("checked_pair_count", 0),
            "passed_pairs": precision.get("passed_pair_count", 0),
            "verified_different_pairs": sum(row.get("status") == "different" for row in precision_pairs),
            "unresolved_pairs": sum(
                row.get("status") in {"alignment_failed", "boolean_failed"} for row in precision_pairs
            ),
            "split_pairs": precision.get("failed_or_split_pair_count", 0),
            "export_roundtrip_valid": export_valid, "max_export_volume_relative_error": max_export_error,
            "export_warning_preserved": (run_dir / "export_failure_workflow_manifest.json").is_file(),
        })
    boolean_runs = [row for row in run_rows if row["precision_mode"] == "boolean"]
    rigid_runs = [row for row in run_rows if row["precision_mode"] == "rigid"]
    admitted = [row for row in inspection if row["status"] == "admitted"]
    stability_path = RESEARCH / "stability_report.json"
    stability = (json.loads(stability_path.read_text(encoding="utf-8"))
                 if stability_path.is_file() else {})
    rigid_path = RESEARCH / "rigid_invariance_report.json"
    rigid_invariance = (json.loads(rigid_path.read_text(encoding="utf-8"))
                        if rigid_path.is_file() else {})
    review_rows = csv_rows(RESEARCH / "human_review" / "review_queue.csv")
    review_strata = Counter(row["selection_stratum"] for row in review_rows)
    covered_ids = {row["id"] for row in boolean_runs + rigid_runs}
    boolean_ids = {row["id"] for row in boolean_runs}
    rigid_only = [row for row in rigid_runs if row["id"] not in boolean_ids]
    summary = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "downloaded_files": sum(row.get("status") in {"downloaded", "verified"} for row in inventory),
        "inspected_files": len(inspection), "admitted_assemblies": len(admitted),
        "admitted_at_least_30_solids": sum(int(row["solids"]) >= 30 for row in admitted),
        "admitted_at_least_50_solids": sum(int(row["solids"]) >= 50 for row in admitted),
        "admitted_at_least_200_solids": sum(int(row["solids"]) >= 200 for row in admitted),
        "rejected_assemblies": [row for row in inspection if row["status"] != "admitted"],
        "boolean_completed_assemblies": len(boolean_runs),
        "boolean_total_solids": sum(row["solid_count"] for row in boolean_runs),
        "boolean_total_final_groups": sum(row["final_groups"] for row in boolean_runs),
        "boolean_assemblies_with_repeated_geometry": sum(
            row["multi_member_groups"] > 0 for row in boolean_runs
        ),
        "boolean_total_multi_member_groups": sum(row["multi_member_groups"] for row in boolean_runs),
        "boolean_total_solids_in_repeated_groups": sum(
            row["solids_in_multi_member_groups"] for row in boolean_runs
        ),
        "boolean_total_checked_pairs": sum(row["checked_pairs"] for row in boolean_runs),
        "boolean_total_split_pairs": sum(row["split_pairs"] for row in boolean_runs),
        "boolean_total_verified_different_pairs": sum(row["verified_different_pairs"] for row in boolean_runs),
        "boolean_total_unresolved_pairs": sum(row["unresolved_pairs"] for row in boolean_runs),
        "boolean_zero_unresolved_assemblies": sum(row["unresolved_pairs"] == 0 for row in boolean_runs),
        "rigid_screened_assemblies": len(rigid_runs),
        "rigid_only_assemblies": len(rigid_only),
        "admitted_assemblies_covered_by_either_tier": len(covered_ids),
        "unclassified_admitted_ids": sorted({row["id"] for row in admitted} - covered_ids),
        "stability": {key: stability.get(key) for key in (
            "run_count", "all_input_order_invariant", "minimum_order_permutation_ari",
            "median_adjacent_threshold_ari", "median_candidate_to_boolean_final_ari"
        )},
        "rigid_invariance": {
            "run_count": len(rigid_invariance.get("runs", [])),
            "all_passed": rigid_invariance.get("all_passed"),
        },
        "human_review": {"queue_size": len(review_rows), "strata": dict(sorted(review_strata.items()))},
        "runs": run_rows,
    }
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    largest = sorted(boolean_runs, key=lambda row: row["solid_count"], reverse=True)[:10]
    lines = [
        "# External assembly classification report", "",
        f"Generated: {summary['generated_at']}", "", "## Coverage", "",
        f"- Downloaded and hash-verified STEP files: {summary['downloaded_files']}",
        f"- Structurally inspected files: {summary['inspected_files']}",
        f"- Admitted assemblies (at least 10 Solid entities): {summary['admitted_assemblies']}",
        f"- Large admitted assemblies (at least 50 Solid entities): {summary['admitted_at_least_50_solids']}",
        f"- Completed Boolean-final assemblies: {summary['boolean_completed_assemblies']}",
        f"- Completed rigid-screening assemblies: {summary['rigid_screened_assemblies']}",
        f"- Admitted assemblies covered by either tier: {summary['admitted_assemblies_covered_by_either_tier']} / {summary['admitted_assemblies']}",
        f"- Solids covered by Boolean-final runs: {summary['boolean_total_solids']}",
        f"- Final geometry groups: {summary['boolean_total_final_groups']}",
        f"- Assemblies containing exact repeated-geometry groups: {summary['boolean_assemblies_with_repeated_geometry']}",
        f"- Exact multi-member groups: {summary['boolean_total_multi_member_groups']}",
        f"- Solids retained in repeated-geometry groups: {summary['boolean_total_solids_in_repeated_groups']}",
        f"- Boolean-checked candidate relations: {summary['boolean_total_checked_pairs']}",
        f"- Relations split by the exact layer: {summary['boolean_total_split_pairs']}",
        f"- Splits with completed Boolean-difference evidence: {summary['boolean_total_verified_different_pairs']}",
        f"- Conservative splits still requiring recall review: {summary['boolean_total_unresolved_pairs']}",
        "", "## Largest completed Boolean-final assemblies", "",
        "| Assembly | Solids | Candidate groups | Final groups | Verified differences | Unresolved | Export warning |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in largest:
        lines.append(f"| {row['id']} | {row['solid_count']} | {row['candidate_groups']} | {row['final_groups']} | {row['verified_different_pairs']} | {row['unresolved_pairs']} | {'yes' if row['export_warning_preserved'] else 'no'} |")
    lines.extend(["", "## Stability and human review", "",
                  f"- Input-order/threshold stability runs: {summary['stability']['run_count'] or 0}",
                  f"- Minimum input-order ARI: {summary['stability']['minimum_order_permutation_ari']}",
                  f"- Median adjacent-threshold ARI: {summary['stability']['median_adjacent_threshold_ari']}",
                  f"- Independent rigid-transform invariance passed: {summary['rigid_invariance']['all_passed']}",
                  f"- Risk-stratified human-review items: {summary['human_review']['queue_size']}",
                  "", "## Interpretation", "",
                  "`Boolean-final` means that candidate merges were refined using rigid alignment and bidirectional OCCT Boolean difference. An export warning does not erase the classification result: the failed roundtrip manifest and per-group validation remain preserved, and the final report clearly distinguishes classification validity from STEP rewrite fidelity.",
                  "", "Every retained multi-member group is connected by passed precision evidence. `Unresolved` relations are conservatively split after alignment or OCCT failure; they protect merge precision but can reduce recall and are therefore placed in the mandatory human-review queue.",
                  "", "`Rigid-screening` is a full-corpus triage result based on rigid alignment. It is deliberately kept separate from Boolean-final output and must not be interpreted as an exact classification baseline.",
                  "", "The unit is an OCCT Solid, not a functional or manufacturing part name. Multi-solid components can therefore contribute several analysis units.", ""])
    (RESEARCH / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in {"runs", "rejected_assemblies"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
