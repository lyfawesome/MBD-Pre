#!/usr/bin/env python3
"""Validate a full native-memory run against a saved Python fast baseline."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.occt_backend import ExactProperties
from geometry_encoder.similarity import PartFeatures, distance_matrix
from geometry_encoder.step_graph import GraphDescriptor


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: check_memory_report.py <mbd_memory_parity> <source.step> <python_report.json>")
    executable = Path(sys.argv[1]).resolve()
    source = Path(sys.argv[2])
    report = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != report["source_sha256"]:
        raise ValueError("source STEP does not match the saved Python baseline")
    config = report["config"]
    if (config["mode"], config["threshold"], config["size_tolerance"], config["wl_iterations"]) != ("strict", 0.12, 0.03, 3):
        raise ValueError("this acceptance harness requires the frozen default fast configuration")
    parts = [PartFeatures(row["part_index"], row["name"], ExactProperties(**row["exact"]),
                          GraphDescriptor(**row["descriptor"]), row.get("source_file", ""))
             for row in report["parts"]]
    # Compute every reference distance with Python, not with the C++ code under test.
    report["parity_distance_matrix"], _ = distance_matrix(parts, "strict", 0.03)
    with tempfile.TemporaryDirectory(prefix="mbd_memory_report_") as folder:
        baseline = Path(folder) / "reference.json"
        baseline.write_text(json.dumps(report, ensure_ascii=True), encoding="utf-8")
        # Keep the caller's relative source path to support MinGW Unicode cwd.
        return subprocess.run([str(executable), str(source), str(baseline)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
