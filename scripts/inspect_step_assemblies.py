#!/usr/bin/env python3
"""Lightweight structural admission check for downloaded STEP assemblies."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.occt_backend import _run_draw, _tcl_path, find_drawexe


MANIFEST = ROOT / "research" / "assembly_sources.json"
OUTPUT = ROOT / "research" / "inspection_results.csv"


def inspect(path: Path, drawexe: Path, minimum_solids: int) -> dict:
    source_text = path.read_text(encoding="latin-1", errors="ignore")
    products = len(re.findall(r"\bPRODUCT\s*\(", source_text, re.I))
    representations = len(re.findall(r"\bSHAPE_REPRESENTATION\s*\(", source_text, re.I))
    script = f"""
pload ALL
NewDocument D
ReadStep D {_tcl_path(path)}
XGetOneShape model D
set solidNames [explode model So]
puts "@@SOLID_COUNT [llength $solidNames]"
puts "@@CHECK_BEGIN"
puts [checkshape model]
puts "@@CHECK_END"
"""
    try:
        output = _run_draw(drawexe, script, timeout=1800)
        match = re.search(r"@@SOLID_COUNT\s+(\d+)", output)
        solids = int(match.group(1)) if match else -1
        check_block = re.search(r"@@CHECK_BEGIN(.*?)@@CHECK_END", output, re.S)
        check_text = check_block.group(1).strip() if check_block else "missing"
        valid = "this shape seems to be valid" in check_text.lower()
        status = "admitted" if solids >= minimum_solids else "rejected_too_few_solids"
        if solids < 0:
            status = "inspection_failed"
        return {"status": status, "solids": solids, "checkshape_valid": valid,
                "product_entities": products, "shape_representations": representations,
                "reason": check_text[-500:].replace("\n", " ")}
    except Exception as exc:
        return {"status": "inspection_failed", "solids": -1, "checkshape_valid": False,
                "product_entities": products, "shape_representations": representations,
                "reason": f"{type(exc).__name__}: {exc}"[-500:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "assemblies")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--minimum-solids", type=int, default=10)
    parser.add_argument("--drawexe", type=Path)
    args = parser.parse_args()
    sources = json.loads(args.manifest.read_text(encoding="utf-8"))["sources"]
    drawexe = find_drawexe(args.drawexe)
    jobs = []
    for source in sources:
        candidates = list(args.input.glob(source["id"] + ".st*"))
        candidates = [path for path in candidates if not path.name.endswith(".part")]
        if candidates:
            jobs.append((source, candidates[0]))

    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(inspect, path, drawexe, args.minimum_solids): (source, path)
                   for source, path in jobs}
        for future in as_completed(futures):
            source, path = futures[future]
            row = {"id": source["id"], "title": source["title"], "path": str(path),
                   "license": source["license"], "inspected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            row.update(future.result())
            rows.append(row)
            print(f"[{row['status']}] {row['id']}: solids={row['solids']}", flush=True)
    order = {source["id"]: index for index, source in enumerate(sources)}
    rows.sort(key=lambda row: order[row["id"]])
    fields = ["id", "title", "status", "solids", "checkshape_valid", "product_entities",
              "shape_representations", "license", "path", "inspected_at", "reason"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    admitted = sum(row["status"] == "admitted" for row in rows)
    print(f"Inspected {len(rows)} files; admitted={admitted}; minimum_solids={args.minimum_solids}")
    return 0 if rows and all(row["status"] != "inspection_failed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
