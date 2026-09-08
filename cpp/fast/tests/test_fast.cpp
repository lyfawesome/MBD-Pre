#include <mbd_fast/fast.hpp>

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {

mbd::fast::PartFeatures cube(int index, double scale = 1.0) {
  mbd::fast::PartFeatures value;
  value.index = index;
  value.label = "part-" + std::to_string(index);
  value.exact = {index, 8 * std::pow(scale, 3), 24 * std::pow(scale, 2),
                 24 * scale, {10 * std::pow(scale, 5),
                              8 * std::pow(scale, 5),
                              6 * std::pow(scale, 5)}};
  value.graph.counts = {{"ADVANCED_FACE", 6}, {"EDGE_CURVE", 12}};
  value.graph.surface_histogram = {{"PLANE", 6}};
  value.graph.curve_histogram = {{"LINE", 24}};
  value.graph.wl_histogram = {{"0:a", 6}, {"1:b", 6}};
  value.graph.wl_family_histogram = value.graph.wl_histogram;
  value.graph.distance_histogram = {0.25, 0.5, 0.25};
  return value;
}

}  // namespace

int main() {
  try {
    const auto result = mbd::fast::group({cube(1), cube(2), cube(3, 2.0)});
    if (result.assignments.size() != 3 ||
        result.assignments[0] != result.assignments[1] ||
        result.assignments[0] == result.assignments[2]) {
      throw std::runtime_error("unexpected strict grouping");
    }
    mbd::fast::Config family;
    family.mode = mbd::fast::Mode::family;
    const auto family_result =
        mbd::fast::group({cube(1), cube(2), cube(3, 2.0)}, family);
    if (family_result.assignments[0] != family_result.assignments[2]) {
      throw std::runtime_error("family mode must ignore uniform scale");
    }
    std::cout << "standalone mbd_fast tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
