#!/usr/bin/env python3
"""Generate one Python reference case and require identical C++ fast/rigid partitions."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.config import WorkflowConfig
from geometry_encoder.occt_backend import ExactProperties, _run_draw, _tcl_path, find_drawexe
from geometry_encoder.precision import load_rigid_geometry, find_rigid_transform
from geometry_encoder.similarity import PartFeatures, density_complete_link, distance_matrix
from geometry_encoder.step_graph import describe_normalized_step
from geometry_encoder.workflow import GeometryWorkflow


def step_text(points: list[tuple[float, float, float]]) -> str:
    rows = ["ISO-10303-21;", "DATA;"]
    for index, point in enumerate(points, 1):
        rows.append(f"#{index}=CARTESIAN_POINT('',({point[0]:.17g},{point[1]:.17g},{point[2]:.17g}));")
        rows.append(f"#{10 + index}=VERTEX_POINT('',#{index});")
    rows.extend(["#20=DIRECTION('',(1.,0.,0.));", "#21=VECTOR('',#20,1.);", "#22=LINE('',#1,#21);"])
    edge_ids = []
    oriented_ids = []
    edge = 30
    for right in range(1, len(points) + 1):
        for left in range(1, right):
            rows.append(f"#{edge}=EDGE_CURVE('',#{10 + left},#{10 + right},#22,.T.);")
            edge_ids.append(edge)
            edge += 1
    for offset, edge_id in enumerate(edge_ids):
        oriented_id = 60 + offset
        rows.append(f"#{oriented_id}=ORIENTED_EDGE('',*,*,#{edge_id},.T.);")
        oriented_ids.append(oriented_id)
    rows.append(f"#80=EDGE_LOOP('',({','.join(f'#{value}' for value in oriented_ids)}));")
    rows.extend(["#81=FACE_OUTER_BOUND('',#80,.T.);", "#82=AXIS2_PLACEMENT_3D('',#1,#20,#20);",
                 "#83=PLANE('',#82);", "#84=ADVANCED_FACE('',(#81),#83,.T.);",
                 "#85=CLOSED_SHELL('',(#84));", "#86=MANIFOLD_SOLID_BREP('fixture',#85);",
                 "ENDSEC;", "END-ISO-10303-21;"])
    return "\n".join(rows) + "\n"


def exact(index: int) -> ExactProperties:
    adjustment = 1.01 if index == 4 else 1.0
    return ExactProperties(index, f"model_{index}", 8.0 * adjustment,
                           24.0 * adjustment, 24.0 * adjustment, (0, 0, 0),
                           (10 * adjustment, 8, 6), (2, 2, 2), 5, 10, 0, 0, 1, 1)


def groups(assignments: list[int]) -> list[dict]:
    grouped: dict[int, list[int]] = {}
    for part, group in enumerate(assignments, 1):
        grouped.setdefault(group, []).append(part)
    return [{"group": group, "parts": parts} for group, parts in sorted(grouped.items())]


def assignments(group_rows: list[dict], count: int) -> list[int]:
    result = [0] * count
    for group in group_rows:
        for part in group["parts"]:
            result[part - 1] = group["group"]
    return result


def same_partition(left: list[int], right: list[int]) -> bool:
    return all((left[a] == left[b]) == (right[a] == right[b])
               for a in range(len(left)) for b in range(a))


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_cpp_parity.py <mbd_geometry_cli>")
    executable = Path(sys.argv[1]).resolve()
    source = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.2, 1.3, 0.0),
              (0.1, 0.4, 2.7), (1.4, 0.3, 1.1)]
    angle = 0.61
    rotated = [(x * math.cos(angle) - y * math.sin(angle) + 7,
                x * math.sin(angle) + y * math.cos(angle) - 4, z + 2.5)
               for x, y, z in source]
    mirrored = [(-x + 5, y - 3, z + 1) for x, y, z in source]
    with tempfile.TemporaryDirectory(prefix="mbd_cpp_parity_") as folder:
        root = Path(folder)
        normalized = root / "normalized_parts"
        normalized.mkdir()
        paths = []
        for index, points in enumerate((source, rotated, mirrored, source), 1):
            path = normalized / f"part_{index:04d}.step"
            path.write_text(step_text(points), encoding="ascii")
            paths.append(path)
        parts = []
        rows = []
        for index, path in enumerate(paths, 1):
            _, descriptor = describe_normalized_step(path)
            item = PartFeatures(index, f"part_{index:04d}", exact(index), descriptor, str(path))
            parts.append(item)
            rows.append({"part_index": index, "name": item.label,
                         "exact": item.exact.to_dict(), "descriptor": descriptor.to_dict()})
        matrix, _ = distance_matrix(parts, "strict", 0.03)
        fast = density_complete_link(matrix, 0.12, stable_keys=[str(i) for i in range(1, 5)])
        geometries = [load_rigid_geometry(path) for path in paths]
        assert find_rigid_transform(geometries[0].points, geometries[1].points, 1e-5,
                                    geometries[0].edges, geometries[1].edges,
                                    geometries[0].faces, geometries[1].faces)
        assert not find_rigid_transform(geometries[0].points, geometries[2].points, 1e-5,
                                        geometries[0].edges, geometries[2].edges,
                                        geometries[0].faces, geometries[2].faces)
        rigid = [1, 1, 2, 1]
        report = {"config": {"mode": "strict", "size_tolerance": 0.03,
                              "threshold": 0.12, "vertex_tolerance": 1e-5},
                  "parts": rows, "parity_distance_matrix": matrix,
                  "candidate_groups": groups(fast), "groups": groups(rigid)}
        report_path = root / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        completed = subprocess.run([str(executable), "parity-report", str(report_path), str(normalized)],
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if completed.returncode:
            print(completed.stdout)
            return completed.returncode
        result = json.loads(completed.stdout)
        if (not result["descriptor_equal"] or result["distance_matrix_max_error"] > 1e-12
                or not result["fast_partition_equal"]
                or not result["rigid_partition_equal"]):
            print(completed.stdout)
            return 2
        renumbered = root / "renumbered.step"
        renumbered.write_text(re.sub(r"#(\d+)", lambda match: f"#{int(match.group(1)) + 1000}",
                                     paths[0].read_text(encoding="ascii")), encoding="ascii")
        original_descriptor = subprocess.run(
            [str(executable), "descriptor", str(paths[0]), "2"], check=True,
            text=True, stdout=subprocess.PIPE).stdout
        renumbered_descriptor = subprocess.run(
            [str(executable), "descriptor", str(renumbered), "2"], check=True,
            text=True, stdout=subprocess.PIPE).stdout
        if json.loads(original_descriptor) != json.loads(renumbered_descriptor):
            return 2
        source_path = root / "two_boxes.step"
        python_output = root / "python_output"
        cpp_output = root / "cpp_output"
        drawexe = find_drawexe()
        _run_draw(drawexe, f"""
pload ALL
box first 2 1 1
tcopy first second
trotate second 0 0 0 0 0 1 37
ttranslate second 5 3 2
compound first second assembly
newmodel
stepwrite 0 assembly {_tcl_path(source_path)}
""")
        python_report = GeometryWorkflow(WorkflowConfig(
            source_path, python_output, drawexe=drawexe, precision_mode="rigid",
            skip_step_export=True,
        )).run()
        native = subprocess.run([str(executable), "run", str(source_path), str(cpp_output), "rigid"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if native.returncode:
            print(native.stdout)
            return native.returncode
        cpp_report = json.loads((cpp_output / "report.json").read_text(encoding="utf-8"))
        count = python_report["part_count"]
        if count != cpp_report["part_count"]:
            return 2
        if not same_partition(assignments(python_report["candidate_groups"], count),
                              assignments(cpp_report["candidate_groups"], count)):
            return 2
        if not same_partition(assignments(python_report["groups"], count),
                              assignments(cpp_report["groups"], count)):
            return 2
    print("Python/C++ fast and rigid partitions are identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
