#pragma once

#include <array>
#include <map>
#include <string>
#include <vector>

namespace mbd::fast {

struct ExactProperties {
  int index{};
  double volume{};
  double area{};
  double edge_length{};
  std::array<double, 3> moments{};
};

struct GraphDescriptor {
  std::map<std::string, int> counts;
  std::map<std::string, int> surface_histogram;
  std::map<std::string, int> curve_histogram;
  std::map<std::string, int> wl_histogram;
  std::map<std::string, int> wl_family_histogram;
  std::vector<double> distance_histogram;
  std::map<std::string, int> graph;
};

struct PartFeatures {
  int index{};
  std::string label;
  ExactProperties exact;
  GraphDescriptor graph;
  std::string source_file;
};

enum class Mode { strict, family };

struct Config {
  Mode mode{Mode::strict};
  double threshold{0.12};
  double strict_size_tolerance{0.03};
};

struct DistanceBreakdown {
  double total{};
  double topology{};
  double geometry{};
  double shape{};
  double size{};
  bool size_gate_failed{};
  [[nodiscard]] double similarity() const;
};

using DistanceMatrix = std::vector<std::vector<double>>;

struct GroupingResult {
  std::vector<int> assignments;
  DistanceMatrix distances;
};

DistanceBreakdown compare(const PartFeatures& left, const PartFeatures& right,
                          Mode mode = Mode::strict,
                          double strict_size_tolerance = 0.03);

DistanceMatrix distance_matrix(const std::vector<PartFeatures>& parts,
                               Mode mode = Mode::strict,
                               double strict_size_tolerance = 0.03);

std::vector<int> density_complete_link(
    const DistanceMatrix& matrix, double threshold,
    const std::vector<std::string>& stable_keys = {});

void verify_assignments(const DistanceMatrix& matrix,
                        const std::vector<int>& assignments, double threshold);

// Main integration entry point. It performs pairwise comparison and stable
// complete-link grouping in one call.
GroupingResult group(const std::vector<PartFeatures>& parts,
                     const Config& config = {});

}  // namespace mbd::fast
