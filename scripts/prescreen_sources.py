#!/usr/bin/env python3
"""Score remote assembly leads before any complete CAD download."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iteration_engine.io import atomic_write_json, utc_now
from iteration_engine.prescreen import prescreen_candidate, summarize_prescreen
from iteration_engine.remote_probe import probe_remote


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "research" / "remote_assembly_candidates.json")
    parser.add_argument("--output", type=Path, default=ROOT / "research" / "prescreen_report.json")
    parser.add_argument("--csv", type=Path, default=ROOT / "research" / "prescreen_report.csv")
    parser.add_argument("--probe-log", type=Path, default=ROOT / "research" / "channel_acquisition_log.csv")
    parser.add_argument("--probe", action="store_true", help="Read at most a bounded sample of direct STEP/ZIP URLs")
    parser.add_argument("--reuse-probes", action="store_true", help="Reuse probes already present in the output report")
    parser.add_argument("--probe-bytes", type=int, default=1_048_576)
    parser.add_argument("--probe-workers", type=int, default=6)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    probes = {}
    if args.reuse_probes and args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        probes.update({
            str(item.get("id", "")): item["remote_probe"]
            for item in previous.get("candidates", []) if item.get("remote_probe")
        })
    if args.probe:
        with ThreadPoolExecutor(max_workers=max(1, args.probe_workers)) as executor:
            futures = {
                executor.submit(
                    probe_remote, str(candidate["download_url"]),
                    str(candidate.get("filename", "")), args.probe_bytes,
                ): str(candidate.get("id", ""))
                for candidate in candidates if candidate.get("download_url")
            }
            for future in as_completed(futures):
                probes[futures[future]] = future.result()

    results = []
    enriched = []
    for original in candidates:
        candidate = dict(original)
        if candidate.get("id") in probes:
            candidate["remote_probe"] = probes[str(candidate["id"])]
        result = prescreen_candidate(candidate)
        results.append(result)
        enriched.append({**candidate, **result.__dict__})

    summary = summarize_prescreen(results)
    summary.update({"schema_version": 1, "generated_at": utc_now(), "candidates": enriched})
    summary.pop("results", None)
    atomic_write_json(args.output, summary)

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "provider", "title", "manufacturing_sector", "sector_confidence",
        "engineering_domains", "possible_components", "assembly_confidence", "assembly_score",
        "decision", "access_status", "license", "landing_url", "download_url", "evidence", "caveats",
    ]
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in enriched:
            output = {key: row.get(key, "") for key in fields}
            for key in ("engineering_domains", "possible_components", "evidence", "caveats"):
                if isinstance(output[key], list):
                    output[key] = " | ".join(str(value) for value in output[key])
            writer.writerow(output)

    probe_fields = [
        "id", "provider", "probe_status", "http_status", "final_url", "total_bytes", "bytes_sampled",
        "step_header", "product_count", "assembly_occurrence_count", "solid_marker_count",
        "archive_entry_count_sampled", "step_entry_count", "error",
    ]
    with args.probe_log.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=probe_fields, lineterminator="\n")
        writer.writeheader()
        for row in enriched:
            probe = row.get("remote_probe")
            if not isinstance(probe, dict):
                continue
            writer.writerow({
                key: row.get(key, "") if key in {"id", "provider"} else probe.get(key, "")
                for key in probe_fields
            })
    print(json.dumps({key: value for key, value in summary.items() if key != "candidates"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
