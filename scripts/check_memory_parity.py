#!/usr/bin/env python3
"""Compare native OCCT descriptors with the unchanged Python STEP reference.

Only this test harness serializes shapes; the library takes in-memory shapes.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.step_graph import describe_normalized_step


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="mbd_memory_parity_") as folder:
        # A relative ASCII filename also works with MinGW under a Unicode cwd.
        subprocess.run([str(executable), "fixtures"], cwd=folder, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        root = Path(folder) / "fixtures"
        rows = json.loads((root / "native.json").read_text())
        maximum_error = 0.0
        for row in rows:
            name = row["name"]
            _, reference = describe_normalized_step(
                root / f"{name}.step", 3, math.cbrt(row["exact"]["volume"]))
            expected = dict(counts=reference.counts,
                            surfaces=reference.surface_histogram,
                            curves=reference.curve_histogram,
                            wl=reference.wl_histogram,
                            family=reference.wl_family_histogram,
                            graph=reference.graph)
            for key, value in expected.items():
                if row["descriptor"][key] != value:
                    raise AssertionError(f"{name}: {key} differs from Python")
            if len(row["histogram"]) != len(reference.distance_histogram):
                raise AssertionError(f"{name}: histogram length differs")
            errors = [abs(a - b) for a, b in
                      zip(row["histogram"], reference.distance_histogram)]
            if not all(math.isfinite(e) and e <= 1e-10 for e in errors):
                raise AssertionError(f"{name}: histogram differs: {errors}")
            maximum_error = max(maximum_error, *errors)
        print(json.dumps(dict(fixtures=len(rows), descriptors_equal=True,
                              histogram_max_error=maximum_error)))


if __name__ == "__main__":
    main()
