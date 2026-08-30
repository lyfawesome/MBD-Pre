from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iteration_engine.config import load_config
from iteration_engine.benchmark import adjusted_rand_index
from iteration_engine.coverage import build_coverage, extract_product_names, geometry_signature
from iteration_engine.discovery import _decision, discover
from iteration_engine.gates import evaluate_gates


class CoverageTest(unittest.TestCase):
    def test_product_names_and_undercoverage_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assemblies = root / "data"
            runs = root / "runs"
            assemblies.mkdir()
            runs.mkdir()
            (assemblies / "fixture.step").write_text(
                "ISO-10303-21;#1=PRODUCT('M6 screw','','',());ENDSEC;END-ISO-10303-21;",
                encoding="ascii",
            )
            output = root / "coverage.json"
            result = build_coverage(
                assemblies, runs,
                {"fastener": ["screw"], "bearing": ["bearing"]},
                output, minimum_sources_per_type=2,
            )
            self.assertEqual(extract_product_names(assemblies / "fixture.step"), ["M6 screw"])
            self.assertEqual(result["missing_semantic_types"], ["bearing"])
            self.assertEqual(result["undercovered_semantic_types"], ["fastener"])
            self.assertEqual(result["coverage_gaps"], ["bearing", "fastener"])
            self.assertEqual(json.loads(output.read_text())["assembly_files_scanned"], 1)

    def test_geometry_signature_is_repeatable(self):
        row = {"volume": "100", "surface_area": "40", "faces": "12",
               "edges": "24", "vertices": "16"}
        self.assertEqual(geometry_signature(row), geometry_signature(dict(row)))


class DiscoveryPolicyTest(unittest.TestCase):
    def test_unknown_license_never_auto_stages(self):
        decision, reason = _decision("unknown", 100, {"mit"}, 1000)
        self.assertEqual((decision, reason), ("manual_review", "license_not_in_allowlist"))

    def test_allowed_license_and_size_stage(self):
        self.assertEqual(_decision("MIT", 100, {"mit"}, 1000)[0], "staged")

    def test_no_coverage_gap_needs_no_network_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = discover([], {}, ["zenodo"], 1, ["MIT"], 1000,
                              root / "candidates.json", root / "attempts.json", 0.1)
            self.assertEqual(result["query_count"], 0)
            self.assertEqual(result["candidates"], [])


class PromotionGateTest(unittest.TestCase):
    def test_human_evidence_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            research = Path(temporary)
            (research / "final_summary.json").write_text(json.dumps({
                "boolean_completed_assemblies": 22,
                "stability": {"minimum_order_permutation_ari": 1.0,
                              "median_adjacent_threshold_ari": 1.0},
                "rigid_invariance": {"all_passed": True},
            }))
            gates = {
                "minimum_order_ari": 1.0, "minimum_threshold_ari": 0.98,
                "minimum_completed_assemblies": 20, "minimum_merge_precision": 0.99,
                "minimum_merge_precision_lower_bound": 0.97,
                "minimum_random_cross_correct_split": 0.97,
                "minimum_random_cross_lower_bound": 0.93,
                "minimum_holdout_partition_ari": 1.0,
                "maximum_holdout_runtime_ratio": 1.10,
            }
            result = evaluate_gates(research, gates, research / "decision.json")
            self.assertEqual(result["decision"], "waiting_for_human_labels")
            self.assertIn("human_merge_precision", result["missing_checks"])
            self.assertIn("holdout_partition_ari", result["missing_checks"])

    def test_partition_metric_is_label_invariant(self):
        self.assertEqual(adjusted_rand_index([1, 1, 2, 3], [8, 8, 4, 9]), 1.0)


class ConfigTest(unittest.TestCase):
    def test_repository_config_loads(self):
        config = load_config()
        self.assertIn("fastener", config.taxonomy)
        self.assertGreaterEqual(len(config.thresholds), 3)


if __name__ == "__main__":
    unittest.main()
