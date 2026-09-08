#include <mbd_fast/fast.hpp>

#include <iostream>

int main() {
  std::vector<mbd::fast::PartFeatures> parts(2);
  for (int i = 0; i < 2; ++i) {
    auto& part = parts[i];
    part.index = i + 1;
    part.label = "part-" + std::to_string(i + 1);
    part.exact = {i + 1, 8.0, 24.0, 24.0, {10.0, 8.0, 6.0}};
    part.graph.counts = {{"ADVANCED_FACE", 6}, {"EDGE_CURVE", 12}};
    part.graph.surface_histogram = {{"PLANE", 6}};
    part.graph.curve_histogram = {{"LINE", 24}};
    part.graph.wl_histogram = {{"0:a", 6}, {"1:b", 6}};
    part.graph.wl_family_histogram = part.graph.wl_histogram;
    part.graph.distance_histogram = {0.25, 0.5, 0.25};
  }

  const auto result = mbd::fast::group(parts);
  for (std::size_t i = 0; i < result.assignments.size(); ++i) {
    std::cout << parts[i].label << " -> group " << result.assignments[i] << '\n';
  }
}
