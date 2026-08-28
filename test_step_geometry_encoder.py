import tempfile
import unittest
import math
import re
from pathlib import Path

from geometry_encoder.occt_backend import ExactProperties, find_drawexe
from geometry_encoder.similarity import PartFeatures, compare, density_complete_link
from geometry_encoder.step_graph import (
    _curve_for_edge, _distance_histogram, describe_normalized_step, parse_step,
)


SAMPLE = """ISO-10303-21;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(2.,1.,1.));
#3=VERTEX_POINT('',#1);
#4=VERTEX_POINT('',#2);
#5=DIRECTION('',(1.,0.,0.));
#6=VECTOR('',#5,1.);
#7=LINE('',#1,#6);
#8=EDGE_CURVE('',#3,#4,#7,.T.);
#9=ORIENTED_EDGE('',*,*,#8,.T.);
#10=EDGE_LOOP('',(#9));
#11=FACE_OUTER_BOUND('',#10,.T.);
#12=AXIS2_PLACEMENT_3D('',#1,#5,#5);
#13=PLANE('',#12);
#14=ADVANCED_FACE('',(#11),#13,.T.);
#15=CLOSED_SHELL('',(#14));
#16=MANIFOLD_SOLID_BREP('sample',#15);
ENDSEC;
END-ISO-10303-21;
"""


def exact(index=1, scale=1.0):
    return ExactProperties(
        index=index, shape_name=f"model_{index}", volume=8 * scale**3,
        area=24 * scale**2, edge_length=24 * scale, center=(0, 0, 0),
        moments=(10 * scale**5, 8 * scale**5, 6 * scale**5), bbox=(2, 2, 2),
        vertices=8, edges=12, wires=6, faces=6, shells=1, solids=1,
    )


class GeometryEncoderTest(unittest.TestCase):
    def test_graph_descriptor_is_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.step"
            path.write_text(SAMPLE, encoding="ascii")
            label_a, descriptor_a = describe_normalized_step(path)
            label_b, descriptor_b = describe_normalized_step(path)
            self.assertEqual(label_a, "sample")
            self.assertEqual(descriptor_a.to_dict(), descriptor_b.to_dict())
            self.assertEqual(descriptor_a.graph["nodes"], 1)
            self.assertEqual(sum(descriptor_a.distance_histogram), 1.0)

    def test_step_entity_renumbering_does_not_change_descriptor(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "original.step"
            renumbered = Path(folder) / "renumbered.step"
            original.write_text(SAMPLE, encoding="ascii")
            renumbered.write_text(
                re.sub(r"#(\d+)", lambda match: f"#{int(match.group(1)) + 10000}", SAMPLE),
                encoding="ascii",
            )
            self.assertEqual(
                describe_normalized_step(original)[1].to_dict(),
                describe_normalized_step(renumbered)[1].to_dict(),
            )

    def test_vertex_pair_distribution_is_rotation_and_order_invariant(self):
        points = [(math.cos(i * 0.37) * (1 + i / 80), math.sin(i * 0.37), i / 31) for i in range(120)]
        angle = 0.713
        rotated = [
            (x * math.cos(angle) - y * math.sin(angle) + 17, x * math.sin(angle) + y * math.cos(angle) - 9, z + 4)
            for x, y, z in reversed(points)
        ]
        left = _distance_histogram(points)
        right = _distance_histogram(rotated)
        for a, b in zip(left, right):
            self.assertAlmostEqual(a, b, places=12)

    def test_identical_part_distance_is_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.step"
            path.write_text(SAMPLE, encoding="ascii")
            _, graph = describe_normalized_step(path)
            left = PartFeatures(1, "a", exact(1), graph, "a.step")
            right = PartFeatures(2, "b", exact(2), graph, "b.step")
            distance = compare(left, right, "strict")
            self.assertAlmostEqual(distance.total, 0.0)
            self.assertAlmostEqual(distance.similarity, 1.0)

    def test_family_mode_ignores_uniform_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            small = Path(folder) / "small.step"
            large = Path(folder) / "large.step"
            small.write_text(SAMPLE.replace("#13=PLANE('',#12);", "#13=CYLINDRICAL_SURFACE('',#12,1.);"), encoding="ascii")
            large.write_text(
                SAMPLE.replace("(2.,1.,1.)", "(4.,2.,2.)").replace(
                    "#13=PLANE('',#12);", "#13=CYLINDRICAL_SURFACE('',#12,2.);"
                ),
                encoding="ascii",
            )
            _, small_graph = describe_normalized_step(small, part_scale=2.0)
            _, large_graph = describe_normalized_step(large, part_scale=4.0)
            left = PartFeatures(1, "a", exact(1, 1.0), small_graph, "a.step")
            right = PartFeatures(2, "b", exact(2, 2.0), large_graph, "b.step")
            self.assertAlmostEqual(compare(left, right, "family").total, 0.0)
            self.assertEqual(compare(left, right, "strict").total, 1.0)

    def test_complete_link_breaks_similarity_chain(self):
        matrix = [[0.0, 0.1, 0.2], [0.1, 0.0, 0.1], [0.2, 0.1, 0.0]]
        assignments = density_complete_link(matrix, threshold=0.11, min_samples=2)
        self.assertEqual(assignments[0], assignments[1])
        self.assertNotEqual(assignments[0], assignments[2])

    def test_complete_link_uses_stable_keys_across_input_permutation(self):
        matrix = [[0.0, 0.1, 0.1], [0.1, 0.0, 0.2], [0.1, 0.2, 0.0]]
        keys = ["a", "b", "c"]
        first = density_complete_link(matrix, 0.11, stable_keys=keys)
        order = [2, 1, 0]
        permuted = [[matrix[a][b] for b in order] for a in order]
        second_raw = density_complete_link(permuted, 0.11, stable_keys=[keys[i] for i in order])
        second = [second_raw[order.index(i)] for i in range(3)]
        first_partition = {frozenset(i for i, value in enumerate(first) if value == group) for group in set(first)}
        second_partition = {frozenset(i for i, value in enumerate(second) if value == group) for group in set(second)}
        self.assertEqual(first_partition, second_partition)

    def test_surface_curve_is_unwrapped_to_basis_curve(self):
        wrapped = SAMPLE.replace("#8=EDGE_CURVE('',#3,#4,#7,.T.);", "#17=SURFACE_CURVE('',#7,(),.CURVE_3D.);\n#8=EDGE_CURVE('',#3,#4,#17,.T.);")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrapped.step"
            path.write_text(wrapped, encoding="ascii")
            entities = parse_step(path)
            self.assertEqual(_curve_for_edge(8, entities).kind, "LINE")

    def test_complex_bspline_entity_is_not_silently_dropped(self):
        complex_record = """ISO-10303-21;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(1.,0.,0.));
#3=(BOUNDED_CURVE() B_SPLINE_CURVE(1,(#1,#2),.UNSPECIFIED.,.F.,.F.) B_SPLINE_CURVE_WITH_KNOTS((2,2),(0.,1.),.UNSPECIFIED.) CURVE() GEOMETRIC_REPRESENTATION_ITEM() RATIONAL_B_SPLINE_CURVE((1.,1.)) REPRESENTATION_ITEM(''));
ENDSEC;
END-ISO-10303-21;
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "complex.step"
            path.write_text(complex_record, encoding="ascii")
            entities = parse_step(path)
            self.assertIn(3, entities)
            self.assertEqual(entities[3].kind, "B_SPLINE_CURVE_WITH_KNOTS")
            self.assertEqual(entities[3].refs, (1, 2))

    def test_occt_backend_is_available(self):
        self.assertTrue(find_drawexe().is_file())


if __name__ == "__main__":
    unittest.main()
