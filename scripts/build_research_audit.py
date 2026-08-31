#!/usr/bin/env python3
"""Materialize auditable source-selection and coverage tables from project artifacts."""

from __future__ import annotations

import csv
import json
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"


def load_csv(path: Path, key: str) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row[key]: row for row in csv.DictReader(handle)}


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def url(source: dict) -> str:
    path = urllib.parse.quote(source["path"], safe="/")
    host = ("https://media.githubusercontent.com/media" if source.get("transport") == "github_media"
            else "https://raw.githubusercontent.com")
    immutable_ref = source.get("source_commit", source["ref"])
    return f"{host}/{source['owner']}/{source['repo']}/{immutable_ref}/{path}"


def rebuild_run_index() -> None:
    """Rebuild the index from immutable per-run reports, avoiding concurrent-writer loss."""
    by_id = {}
    for run_root in (ROOT / "runs" / "rigid_corpus", ROOT / "runs" / "assembly_corpus"):
        for report_path in sorted(run_root.glob("*/report.json")):
            run_dir = report_path.parent
            report = json.loads(report_path.read_text(encoding="utf-8"))
            groups = report.get("groups", [])
            precision_path = run_dir / "precision_report.json"
            precision = json.loads(precision_path.read_text(encoding="utf-8")) if precision_path.is_file() else {}
            manifest_path = run_dir / "workflow_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            by_id[run_dir.name] = {
                "id": run_dir.name, "status": manifest.get("status", "completed"),
                "solids": report.get("part_count", ""),
                "candidate_groups": report.get("candidate_group_count", ""),
                "final_groups": report.get("group_count", ""),
                "multi_member_groups": sum(group.get("part_count", 0) > 1 for group in groups),
                "solids_in_multi_member_groups": sum(
                    group.get("part_count", 0) for group in groups if group.get("part_count", 0) > 1
                ),
                "unresolved_pairs": sum(
                    pair.get("status") in {"alignment_failed", "boolean_failed"}
                    for pair in precision.get("pairs", [])
                ),
                "precision_mode": report.get("config", {}).get("precision_mode", ""),
                "threshold": report.get("config", {}).get("threshold", ""),
                "elapsed_seconds": round(sum(
                    float(stage.get("duration_seconds", 0.0)) for stage in manifest.get("stages", [])
                ), 3),
                "started_at": manifest.get("started_at", ""),
                "finished_at": manifest.get("completed_at", ""),
                "source": report.get("source", ""), "output": str(run_dir), "error": "",
            }
    fields = ["id", "status", "solids", "candidate_groups", "final_groups",
              "multi_member_groups", "solids_in_multi_member_groups", "unresolved_pairs", "precision_mode",
              "threshold", "elapsed_seconds", "started_at", "finished_at", "source", "output", "error"]
    write_csv(RESEARCH / "classification_runs.csv", [by_id[key] for key in sorted(by_id)], fields)


def main() -> int:
    rebuild_run_index()
    manifest = json.loads((RESEARCH / "assembly_sources.json").read_text(encoding="utf-8"))
    inventory = load_csv(RESEARCH / "raw_data_file_inventory.csv", "id")
    inspection = load_csv(RESEARCH / "inspection_results.csv", "id")
    runs = load_csv(RESEARCH / "classification_runs.csv", "id")
    catalog = []
    for source in manifest["sources"]:
        acquired = inventory.get(source["id"], {})
        checked = inspection.get(source["id"], {})
        classified = runs.get(source["id"], {})
        catalog.append({
            "id": source["id"], "title": source["title"], "repository": f"{source['owner']}/{source['repo']}",
            "source_url": url(source), "format": "STEP", "license": source["license"],
            "tier": source["tier"], "source_branch": source["ref"],
            "source_commit": source.get("source_commit", ""),
            "expected_bytes": source["expected_bytes"],
            "expected_sha256": source.get("expected_sha256", ""),
            "acquisition_status": acquired.get("status", "pending"),
            "sha256": acquired.get("sha256", ""), "solid_count": checked.get("solids", ""),
            "inspection_status": checked.get("status", "pending"),
            "classification_status": classified.get("status", "pending"),
            "final_group_count": classified.get("final_groups", ""),
            "multi_member_groups": classified.get("multi_member_groups", ""),
            "solids_in_multi_member_groups": classified.get("solids_in_multi_member_groups", ""),
            "unresolved_pairs": classified.get("unresolved_pairs", ""),
            "selection_reason": (source.get("admission_note") or
                                 "Multi-solid open-source mechanism suitable for repeated-part grouping evaluation."),
        })
    write_csv(RESEARCH / "source_catalog.csv", catalog,
              ["id", "title", "repository", "source_url", "format", "license", "tier",
               "source_branch", "source_commit", "expected_bytes", "expected_sha256",
               "acquisition_status", "sha256", "solid_count", "inspection_status",
               "classification_status", "final_group_count", "multi_member_groups",
               "solids_in_multi_member_groups", "unresolved_pairs", "selection_reason"])

    coverage = [
        {"question":"Can the file be legally and reproducibly acquired?","primary_evidence":"source_catalog.csv; raw_data_file_inventory.csv","acceptance":"Known license, stable URL, SHA-256"},
        {"question":"Is it a real multi-part assembly rather than an isolated standard part?","primary_evidence":"inspection_results.csv","acceptance":"At least 10 OCCT Solid entities"},
        {"question":"Does the algorithm find repeated geometry?","primary_evidence":"classification_runs.csv; per-run report.json","acceptance":"Completed run; inspect multi-member groups"},
        {"question":"Are within-group merges geometrically defensible?","primary_evidence":"precision_report.json; Boolean subset","acceptance":"Rigid/Boolean verification passes"},
        {"question":"Could equivalent parts have been split across groups?","primary_evidence":"human_review/review_queue.csv near-miss stratum","acceptance":"Cross-group near-neighbour audit"},
        {"question":"Is the result stable?","primary_evidence":"stability_report.json","acceptance":"Order ARI=1 and threshold plateau documented"},
        {"question":"Can a human review it without opening every STEP?","primary_evidence":"human_review/index.html","acceptance":"Risk-stratified contact sheets and CSV export"},
    ]
    write_csv(RESEARCH / "question_coverage.csv", coverage,
              ["question", "primary_evidence", "acceptance"])

    complementarity = []
    roles = {
        "GitHub upstream STEP assemblies":"Primary downloadable B-Rep data with explicit project licenses",
        "Quidities gallery":"Discovery and independent assembly-size cross-check; not used as raw geometry",
        "AutoMate Zenodo corpus":"Large-scale expansion source with assembly graphs and STEP parts",
        "NIST PMI examples":"Small authoritative STEP conformance and interoperability controls",
        "Local OCCT inspection":"Independent Solid count, validity and roundtrip evidence",
        "Human risk queue":"Semantic/visual adjudication of merges and missed merges",
    }
    for name, role in roles.items():
        complementarity.append({"source_class": name, "provenance": "primary" if name.startswith("GitHub") or name.startswith("AutoMate") or name.startswith("NIST") else "derived",
                                "geometry": "yes" if name.startswith(("GitHub", "AutoMate", "NIST")) else "no",
                                "licenses": "yes" if name.startswith(("GitHub", "AutoMate", "NIST")) else "supporting",
                                "assembly_structure": "yes" if name.startswith(("GitHub", "AutoMate")) else "supporting",
                                "validation_role": role})
    write_csv(RESEARCH / "source_complementarity_matrix.csv", complementarity,
              ["source_class", "provenance", "geometry", "licenses", "assembly_structure", "validation_role"])

    admitted = [row for row in catalog if row["tier"] == "core"]
    quarantined = [row for row in catalog if row["tier"] != "core"]
    lines = [
        "# Source selection audit", "", "## Admission policy", "",
        "Admit openly downloadable STEP assemblies with an explicit reusable license and at least 10 OCCT Solid entities. Prefer complete mechanisms with repeated hardware or repeated structural parts. Preserve every failure and exclusion instead of silently dropping it.",
        "", "## Current inventory", "",
        f"- Core candidates: {len(admitted)}", f"- Quarantined candidates: {len(quarantined)}",
        f"- Downloaded or verified: {sum(row['acquisition_status'] in {'downloaded','verified'} for row in catalog)}",
        f"- Structurally admitted: {sum(row['inspection_status'] == 'admitted' for row in catalog)}",
        f"- Classified: {sum(row['classification_status'].startswith('completed') for row in catalog)}",
        "", "## Explicit exclusions and deferrals", "",
    ]
    for row in quarantined:
        lines.append(f"- `{row['id']}`: quarantined because the repository license could not be established.")
    for lead in manifest["large_corpus_leads"]:
        lines.append(f"- {lead['title']}: {lead['status']}; {lead['reason']}")
    lines.extend(["", "## Known limitations", "",
                  "GitHub-hosted assemblies are heterogeneous and do not provide authoritative pair labels. Therefore geometric precision evidence is combined with a risk-stratified human queue. The corpus measures geometric grouping, not functional part-name classification.", ""])
    (RESEARCH / "source_selection_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Catalogued {len(catalog)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
