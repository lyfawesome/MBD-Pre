import json
import hashlib
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from geometry_encoder.config import WorkflowConfig
from geometry_encoder.occt_backend import (
    _run_draw, _tcl_path, find_drawexe, verify_rigid_pairs_with_boolean,
)
from geometry_encoder.precision import (
    PairVerification, RigidTransform, _axis_angle, find_rigid_transform,
)
from geometry_encoder.telemetry import WorkflowRecorder
from geometry_encoder.workflow import (
    GeometryWorkflow, _precision_checkpoint, _restore_precision_result,
    _write_precision_checkpoint,
)


class PrecisionUnitTest(unittest.TestCase):
    def test_failed_boolean_batch_retries_singletons_in_shared_pool(self):
        identity = RigidTransform(
            rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            translation=(0.0, 0.0, 0.0), axis=(1.0, 0.0, 0.0), angle_degrees=0.0,
            rms_vertex_error=0.0, max_vertex_error=0.0,
        )
        pairs = [PairVerification(1, 1, index, "aligned", "", 8, identity)
                 for index in range(2, 6)]
        attempted_batch_sizes = []
        checkpoint_sizes = []

        def fake_draw(_drawexe, script, timeout=3600):
            batch_size = script.count("@@FORWARD_BEGIN")
            attempted_batch_sizes.append(batch_size)
            if batch_size > 1:
                raise TimeoutError("synthetic batch timeout")
            return "@@FORWARD_BEGIN 1\nMass : 0\n@@FORWARD_END 1\n" \
                   "@@REVERSE_BEGIN 1\nMass : 0\n@@REVERSE_END 1\n"

        with patch("geometry_encoder.occt_backend._run_draw", side_effect=fake_draw):
            verify_rigid_pairs_with_boolean(
                Path("source.step"), pairs, {index: 1.0 for index in range(1, 6)},
                Path("DRAWEXE"), workers=2, normalized_dir=Path("cache"),
                result_callback=lambda completed: checkpoint_sizes.append(len(completed)),
            )

        self.assertEqual(sorted(attempted_batch_sizes), [1, 1, 1, 1, 4])
        self.assertEqual(checkpoint_sizes, [1, 1, 1, 1])
        self.assertTrue(all(pair.status == "verified" and pair.passed for pair in pairs))

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

    def test_rigid_fingerprint_tolerates_adjacent_quantization_bins(self):
        source = [
            (0.37286677651407407, 0.6244865760167085, 0.22795976272212315),
            (0.2026252770582384, 0.3859661844073685, 0.1864784582738538),
            (0.1125726393278852, 0.14255163554197614, 0.2283446307104201),
            (0.9408962666789277, 0.5210990853341416, 0.03283467141067353),
            (0.15335044968564993, 0.3925332051210709, 0.3830499535657014),
            (0.39061823252398575, 0.961947452384876, 0.1684877845891668),
            (0.45370827333883534, 0.7969009090293485, 0.3929753406948706),
            (0.920628573983454, 0.6769454116932154, 0.26607099468967854),
        ]
        target = [
            (3.860685706834955, -2.28613401492528, 2.227959762394246),
            (3.8931793583360643, -2.5773698443703426, 2.186478458996319),
            (3.9886416008186374, -2.8187141634836768, 2.228344630077618),
            (4.352610714917745, -1.9838820327419835, 2.0328346717111767),
            (3.8521096588238186, -2.6053772370999, 2.383049952610936),
            (3.6486080266277336, -2.0230408475085344, 2.1684877851207487),
            (3.805766475640744, -2.1037993558174226, 2.3929753402215805),
            (4.233476008148363, -1.8813843307844362, 2.266070994860232),
        ]
        transform = find_rigid_transform(source, target, 1e-5)
        self.assertIsNotNone(transform)
        self.assertLess(transform.max_vertex_error, 2e-9)

    def test_configuration_rejects_invalid_precision_mode(self):
        config = WorkflowConfig(Path("x.step"), Path("out"), precision_mode="guess")
        with self.assertRaises(ValueError):
            config.validate()
        with self.assertRaises(ValueError):
            WorkflowConfig(Path("x.step"), Path("out"), precision_workers=0).validate()
        with self.assertRaises(ValueError):
            WorkflowConfig(
                Path("x.step"), Path("out"), export_volume_relative_tolerance=0.0,
            ).validate()


class TelemetryTest(unittest.TestCase):
    def test_precision_checkpoint_is_signature_scoped_and_restorable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "precision_checkpoint.json"
            signature = {"source_sha256": "abc", "threshold": 0.12}
            pair = {"status": "verified", "reason": "passed", "vertex_count": 8,
                    "forward_difference_volume": 0.0, "reverse_difference_volume": 0.0,
                    "boolean_relative_error": 0.0, "passed": True}
            _write_precision_checkpoint(path, signature, {"1:2": pair})
            self.assertEqual(_precision_checkpoint(path, signature)["1:2"], pair)
            self.assertEqual(_precision_checkpoint(path, {"source_sha256": "changed"}), {})
            item = SimpleNamespace()
            _restore_precision_result(item, pair)
            self.assertEqual(item.status, "verified")
            self.assertTrue(item.passed)

    def test_legacy_checkpoint_migration_reuses_only_resolved_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "precision_checkpoint.json"
            signature = {
                "schema": 2, "source_sha256": "abc",
                "algorithm_revision": "rigid-fingerprint-adjacent-bins-v2",
            }
            path.write_text(json.dumps({
                "schema": 1,
                "signature": {"schema": 1, "source_sha256": "abc"},
                "pairs": {
                    "1:2": {"status": "verified", "passed": True},
                    "1:3": {"status": "different", "passed": False},
                    "1:4": {"status": "alignment_failed", "passed": False},
                    "1:5": {"status": "boolean_failed", "passed": False},
                },
            }), encoding="utf-8")
            migrated = _precision_checkpoint(path, signature)
            self.assertEqual(set(migrated), {"1:2", "1:3"})

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

    def test_failed_gate_marks_manifest_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            recorder = WorkflowRecorder(output, {"mode": "test"}, "abc")
            with self.assertRaises(RuntimeError):
                recorder.gate("expected_failure", False, {"reason": "test"})
            manifest = json.loads((output / "workflow_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse(manifest["quality_gates"][0]["passed"])


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
