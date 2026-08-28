import json
import hashlib
import math
import tempfile
import unittest
from pathlib import Path

from geometry_encoder.config import WorkflowConfig
from geometry_encoder.occt_backend import _run_draw, _tcl_path, find_drawexe
from geometry_encoder.precision import _axis_angle, find_rigid_transform
from geometry_encoder.telemetry import WorkflowRecorder
from geometry_encoder.workflow import GeometryWorkflow


class PrecisionUnitTest(unittest.TestCase):
    def test_axis_angle_is_stable_near_180_degrees(self):
        axis = (0.5355737329905428, 0.8444884703360814, -2.0e-12)
        norm = math.sqrt(sum(value * value for value in axis))
        x, y, z = (value / norm for value in axis)
        angle = math.pi - 2.0e-11
        cosine, sine, one_minus = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
        matrix = (
            (cosine + x*x*one_minus, x*y*one_minus-z*sine, x*z*one_minus+y*sine),
            (y*x*one_minus+z*sine, cosine+y*y*one_minus, y*z*one_minus-x*sine),
            (z*x*one_minus-y*sine, z*y*one_minus+x*sine, cosine+z*z*one_minus),
        )
        recovered_axis, recovered_degrees = _axis_angle(matrix)
        recovered_angle = math.radians(recovered_degrees)
        rx, ry, rz = recovered_axis
        rc, rs, ro = math.cos(recovered_angle), math.sin(recovered_angle), 1.0-math.cos(recovered_angle)
        reconstructed = (
            (rc+rx*rx*ro, rx*ry*ro-rz*rs, rx*rz*ro+ry*rs),
            (ry*rx*ro+rz*rs, rc+ry*ry*ro, ry*rz*ro-rx*rs),
            (rz*rx*ro-ry*rs, rz*ry*ro+rx*rs, rc+rz*rz*ro),
        )
        self.assertLess(max(abs(matrix[i][j]-reconstructed[i][j]) for i in range(3) for j in range(3)), 1e-12)

    def test_rigid_transform_recovers_rotation_and_translation(self):
        source = [
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, 0.0, 3.0), (1.2, 0.4, 2.1),
        ]
        angle = 0.61
        target = [
            (
                x * math.cos(angle) - y * math.sin(angle) + 7.0,
                x * math.sin(angle) + y * math.cos(angle) - 4.0,
                z + 2.5,
            )
            for x, y, z in source
        ]
        transform = find_rigid_transform(source, target, 1e-8)
        self.assertIsNotNone(transform)
        self.assertLess(transform.max_vertex_error, 1e-10)

    def test_chiral_mirror_is_not_accepted_as_rigid_rotation(self):
        source = [
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.2, 1.3, 0.0),
            (0.1, 0.4, 2.7), (1.4, 0.3, 1.1),
        ]
        mirrored = [(-x + 5.0, y - 3.0, z + 1.0) for x, y, z in source]
        self.assertIsNone(find_rigid_transform(source, mirrored, 1e-8))

    def test_configuration_rejects_invalid_precision_mode(self):
        config = WorkflowConfig(Path("x.step"), Path("out"), precision_mode="guess")
        with self.assertRaises(ValueError):
            config.validate()
        with self.assertRaises(ValueError):
            WorkflowConfig(Path("x.step"), Path("out"), precision_workers=0).validate()


class TelemetryTest(unittest.TestCase):
    def test_manifest_records_stages_gates_and_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            recorder = WorkflowRecorder(output, {"mode": "test"}, "abc")
            artifact = output / "artifact.txt"
            artifact.write_text("verified", encoding="utf-8")
            with recorder.stage("sample") as stage:
                stage["metrics"] = {"items": 1}
            recorder.gate("sample_gate", True, {"items": 1})
            recorder.collect_artifacts([artifact])
            recorder.complete({"items": 1})
            manifest = json.loads((output / "workflow_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["stages"][0]["status"], "completed")
            self.assertTrue(manifest["quality_gates"][0]["passed"])
            self.assertEqual(manifest["artifacts"][0]["sha256"], hashlib.sha256(b"verified").hexdigest())


class OcctWorkflowIntegrationTest(unittest.TestCase):
    def test_two_rotated_boxes_group_and_pass_boolean_roundtrip(self):
        drawexe = find_drawexe()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "two_boxes.step"
            output = root / "output"
            script = f"""
pload ALL
box first 2 1 1
tcopy first second
trotate second 0 0 0 0 0 1 37
ttranslate second 5 3 2
compound first second assembly
newmodel
stepwrite 0 assembly {_tcl_path(source)}
"""
            _run_draw(drawexe, script)
            report = GeometryWorkflow(WorkflowConfig(
                source, output, drawexe=drawexe, precision_mode="boolean",
                vertex_tolerance=1e-5, boolean_relative_tolerance=1e-6,
            )).run()
            self.assertEqual(report["part_count"], 2)
            self.assertEqual(report["candidate_group_count"], 1)
            self.assertEqual(report["group_count"], 1)
            precision = json.loads((output / "precision_report.json").read_text(encoding="utf-8"))
            self.assertEqual(precision["passed_pair_count"], 1)
            manifest = json.loads((output / "grouped_steps" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["validation"][0]["actual_solid_count"], 2)
            self.assertTrue(manifest["validation"][0]["valid"])
            workflow = json.loads((output / "workflow_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["status"], "completed")


if __name__ == "__main__":
    unittest.main()
