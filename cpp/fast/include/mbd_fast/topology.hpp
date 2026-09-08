#pragma once

#include "fast.hpp"

namespace mbd::fast {

// Geometry-kernel-neutral topology. Each edge index identifies one topological
// edge; a seam occurs twice in a face's edge_uses. Coordinates share one unit.
struct GeometryLabel {
  std::string kind;
  std::vector<double> lengths;
  std::vector<double> angles; // radians
};

struct FaceTopology {
  GeometryLabel surface;
  int bounds{};
  std::vector<int> edge_uses;
};

struct PartTopology {
  std::vector<FaceTopology> faces;
  std::vector<GeometryLabel> edges;
  std::vector<std::array<double, 3>> vertices;
  std::map<std::string, int> counts;
};

GraphDescriptor describe_topology(const PartTopology& topology,
                                  int wl_iterations = 3,
                                  double part_scale = 1.0);

} // namespace mbd::fast
