#!/usr/bin/env python3
"""Run the repository workflow over every structurally admitted assembly."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSPECTION = ROOT / "research" / "inspection_results.csv"
RUN_INDEX = ROOT / "research" / "classification_runs.csv"
CURRENT_PRECISION_ALGORITHM_REVISION = "rigid-fingerprint-adjacent-bins-v2"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def completed_report(output: Path, source: Path, mode: str, threshold: float) -> dict | None:
    report_path = output / "report.json"
    manifest_path = output / "workflow_manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    config = report.get("config", {})
    if mode != "off":
        method_path = output / "method.json"
        if not method_path.is_file():
            return None
        try:
            method = json.loads(method_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if method.get("precision_algorithm_revision") != CURRENT_PRECISION_ALGORITHM_REVISION:
            return None
    if (manifest.get("status") in {"completed", "completed_with_export_warning"}
            and Path(report.get("source", "")).resolve() == source.resolve()
            and config.get("precision_mode") == mode and float(config.get("threshold", -1)) == threshold):
        return report
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspection", type=Path, default=INSPECTION)
    parser.add_argument("--runs", type=Path, default=ROOT / "runs" / "assembly_corpus")
    parser.add_argument("--index", type=Path, default=RUN_INDEX)
    parser.add_argument("--precision-mode", choices=("boolean", "rigid", "off"), default="boolean")
    parser.add_argument("--threshold", type=float, default=0.12)
    parser.add_argument("--precision-workers", type=int, default=4)
    parser.add_argument("--export-volume-relative-tolerance", type=float, default=2e-5)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--max-solids", type=int)
    parser.add_argument("--allow-unknown-geometry", action="store_true")
    parser.add_argument("--skip-step-export", action="store_true",
                        help="Keep classification artifacts but omit grouped STEP export")
    args = parser.parse_args()

    with args.inspection.open(encoding="utf-8", newline="") as handle:
        candidates = [row for row in csv.DictReader(handle) if row["status"] == "admitted"]
    if args.ids:
        selected = set(args.ids)
        candidates = [row for row in candidates if row["id"] in selected]
    if args.max_solids is not None:
        candidates = [row for row in candidates if int(row["solids"]) <= args.max_solids]
    args.runs.mkdir(parents=True, exist_ok=True)
    results = []
    for row in candidates:
        source = Path(row["path"])
        output = args.runs / row["id"]
        started = now()
        report = completed_report(output, source, args.precision_mode, args.threshold)
        status = "reused" if report else "running"
        error = ""
        if report is None:
            previous_report_path = output / "report.json"
            if previous_report_path.is_file():
                try:
                    previous_report = json.loads(previous_report_path.read_text(encoding="utf-8"))
                    previous_mode = previous_report.get("config", {}).get("precision_mode", "unknown")
                    archive = args.runs.parent / "screening_archive" / row["id"] / previous_mode
                    archive.mkdir(parents=True, exist_ok=True)
                    for name in ("report.json", "precision_report.json", "data_quality.json",
                                 "method.json", "workflow_manifest.json"):
                        source_artifact = output / name
                        if source_artifact.is_file():
                            shutil.copy2(source_artifact, archive / name)
                except (OSError, json.JSONDecodeError):
                    pass
            command = [sys.executable, str(ROOT / "step_geometry_encoder.py"), str(source),
                       "--output", str(output), "--threshold", str(args.threshold),
                       "--precision-mode", args.precision_mode,
                       "--precision-workers", str(args.precision_workers),
                       "--export-volume-relative-tolerance", str(args.export_volume_relative_tolerance)]
            if (output / "cache_manifest.json").is_file():
                command.append("--reuse-cache")
            if args.allow_unknown_geometry:
                command.append("--allow-unknown-geometry")
            if args.skip_step_export:
                command.append("--skip-step-export")
            print(f"[running] {row['id']} solids={row['solids']}", flush=True)
            begin = time.monotonic()
            completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, check=False)
            console = completed.stdout
            elapsed = time.monotonic() - begin
            if completed.returncode == 0:
                report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                status = "completed"
            elif ((output / "parts.csv").is_file()
                  and (output / "grouped_steps" / "manifest.json").is_file()):
                failed_manifest = output / "workflow_manifest.json"
                if failed_manifest.is_file():
                    shutil.copy2(failed_manifest, output / "export_failure_workflow_manifest.json")
                fallback = command + ["--skip-step-export", "--reuse-cache"]
                retried = subprocess.run(fallback, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, check=False)
                console += "\n@@EXPORT_FALLBACK@@\n" + retried.stdout
                elapsed = time.monotonic() - begin
                if retried.returncode == 0:
                    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                    status = "completed_with_export_warning"
                    error = completed.stdout[-1000:].replace("\n", " ")
                else:
                    status = "failed"
                    error = retried.stdout[-1000:].replace("\n", " ")
                    report = {}
            else:
                status = "failed"
                error = completed.stdout[-1000:].replace("\n", " ")
                report = {}
            (output / "batch_console.log").write_text(console, encoding="utf-8")
        else:
            elapsed = 0.0
        result = {
            "id": row["id"], "status": status, "source": str(source),
            "solids": row["solids"], "candidate_groups": report.get("candidate_group_count", ""),
            "final_groups": report.get("group_count", ""),
            "precision_mode": args.precision_mode, "threshold": args.threshold,
            "elapsed_seconds": round(elapsed, 3), "started_at": started, "finished_at": now(),
            "output": str(output), "error": error,
        }
        results.append(result)
        print(f"[{status}] {row['id']}: {result['candidate_groups']} -> {result['final_groups']} groups", flush=True)

    fields = ["id", "status", "solids", "candidate_groups", "final_groups", "precision_mode",
              "threshold", "elapsed_seconds", "started_at", "finished_at", "source", "output", "error"]
    previous = {}
    if args.index.is_file():
        with args.index.open(encoding="utf-8", newline="") as handle:
            previous = {row["id"]: row for row in csv.DictReader(handle)}
    previous.update({row["id"]: row for row in results})
    merged = [previous[key] for key in sorted(previous)]
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in merged)
    return 1 if any(row["status"] == "failed" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
