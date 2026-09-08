#pragma once

#include <mbd_fast/fast.hpp>
#include <stdexcept>

namespace mbd {

using ExactProperties = fast::ExactProperties;
using GraphDescriptor = fast::GraphDescriptor;
using PartFeatures = fast::PartFeatures;
using DistanceBreakdown = fast::DistanceBreakdown;

inline DistanceBreakdown compare(const PartFeatures& left, const PartFeatures& right,
                                 const std::string& mode = "strict",
                                 double strict_size_tolerance = 0.03) {
  return fast::compare(left, right,
                       mode == "strict" ? fast::Mode::strict :
                       mode == "family" ? fast::Mode::family :
                       throw std::invalid_argument("mode must be strict or family"),
                       strict_size_tolerance);
}

inline std::vector<std::vector<double>> distance_matrix(
    const std::vector<PartFeatures>& parts, const std::string& mode,
    double strict_size_tolerance = 0.03) {
  return fast::distance_matrix(parts,
                               mode == "strict" ? fast::Mode::strict :
                               mode == "family" ? fast::Mode::family :
                               throw std::invalid_argument("mode must be strict or family"),
                               strict_size_tolerance);
}

inline std::vector<int> density_complete_link(
    const std::vector<std::vector<double>>& matrix, double threshold,
    const std::vector<std::string>& stable_keys = {}) {
  return fast::density_complete_link(matrix, threshold, stable_keys);
}

inline void verify_assignments(const std::vector<std::vector<double>>& matrix,
                               const std::vector<int>& assignments, double threshold) {
  fast::verify_assignments(matrix, assignments, threshold);
}

}  // namespace mbd
