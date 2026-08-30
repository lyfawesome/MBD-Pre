#!/usr/bin/env python3
"""Reclassify assemblies after independently rotating and translating every solid."""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.occt_backend import _run_draw, _tcl_path, find_drawexe
from evaluate_stability import adjusted_rand_index, final_assignments


def transformed_step(source: Path, destination: Path, part_count: int, drawexe: Path,
                     seed: str) -> list[dict]:
    rng = random.Random(seed)
    lines = [
        "pload ALL", "NewDocument TransformDoc", f"ReadStep TransformDoc {_tcl_path(source)}",
        "XGetOneShape model TransformDoc", "explode model So",
    ]
    transforms = []
    names = []
    for index in range(1, part_count + 1):
        axis = [rng.uniform(-1.0, 1.0) for _ in range(3)]
        norm = math.sqrt(sum(value * value for value in axis)) or 1.0
        axis = [value / norm for value in axis]
        angle = rng.uniform(7.0, 353.0)
        translation = [rng.uniform(-250.0, 250.0) for _ in range(3)]
        name = f"moved_{index}"
        names.append(name)
        lines.extend([
            f"tcopy model_{index} {name}",
            f"trotate {name} 0 0 0 {axis[0]:.17g} {axis[1]:.17g} {axis[2]:.17g} {angle:.17g}",
            f"ttranslate {name} {translation[0]:.17g} {translation[1]:.17g} {translation[2]:.17g}",
        ])
        transforms.append({"part": index, "axis": axis, "angle_degrees": angle,
                           "translation": translation})
    lines.extend([
        f"compound {' '.join(names)} transformed_model", "newmodel",
        f"stepwrite 0 transformed_model {_tcl_path(destination)}",
    ])
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_draw(drawexe, "\n".join(lines), timeout=1800)
    return transforms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-runs", type=Path, default=ROOT / "runs" / "assembly_corpus")
    parser.add_argument("--output-runs", type=Path, default=ROOT / "runs" / "rigid_invariance")
    parser.add_argument("--inputs", type=Path, default=ROOT / "runs" / "rigid_invariance_inputs")
    parser.add_argument("--report", type=Path, default=ROOT / "research" / "rigid_invariance_report.json")
    parser.add_argument("--ids", nargs="*", default=["so100_follower", "hope_arm", "scalenode_rpi4"])
    parser.add_argument("--precision-workers", type=int, default=4)
    parser.add_argument("--drawexe", type=Path)
    args = parser.parse_args()
    drawexe = find_drawexe(args.drawexe)
    results = []
    for dataset_id in args.ids:
        baseline_dir = args.baseline_runs / dataset_id
        baseline = json.loads((baseline_dir / "report.json").read_text(encoding="utf-8"))
        source = Path(baseline["source"])
        transformed = args.inputs / f"{dataset_id}.step"
        seed = f"MBD-Pre-rigid-invariance-v1:{dataset_id}"
        print(f"[transform] {dataset_id}", flush=True)
        transforms = transformed_step(source, transformed, baseline["part_count"], drawexe, seed)
        output = args.output_runs / dataset_id
        command = [
            sys.executable, str(ROOT / "step_geometry_encoder.py"), str(transformed),
            "--output", str(output), "--threshold", str(baseline["config"]["threshold"]),
            "--precision-mode", "boolean", "--precision-workers", str(args.precision_workers),
            "--skip-step-export",
        ]
        print(f"[classify] {dataset_id}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, check=False)
        (output / "console.log").write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            results.append({"id": dataset_id, "status": "failed", "error": completed.stdout[-2000:]})
            continue
        moved = json.loads((output / "report.json").read_text(encoding="utf-8"))
        if moved["part_count"] != baseline["part_count"]:
            results.append({"id": dataset_id, "status": "failed", "error": "solid count changed"})
            continue
        ari = adjusted_rand_index(final_assignments(baseline), final_assignments(moved))
        transform_path = output / "applied_transforms.json"
        transform_path.write_text(json.dumps(transforms, indent=2), encoding="utf-8")
        results.append({
            "id": dataset_id, "status": "passed" if ari >= 0.999999999999 else "changed",
            "part_count": baseline["part_count"], "baseline_group_count": baseline["group_count"],
            "transformed_group_count": moved["group_count"], "adjusted_rand_index": ari,
            "seed": seed, "transformed_step": str(transformed),
        })
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "all_passed": bool(results) and all(row["status"] == "passed" for row in results),
        "runs": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
