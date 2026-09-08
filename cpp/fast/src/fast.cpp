#include "mbd_fast/fast.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <limits>
#include <queue>
#include <set>
#include <stdexcept>
#include <tuple>
#include <unordered_map>
#include <utility>

namespace mbd::fast {
namespace {

double cosine_distance(const std::map<std::string, int>& left,
                       const std::map<std::string, int>& right) {
  long double dot = 0.0L, left_norm = 0.0L, right_norm = 0.0L;
  for (const auto& [key, value] : left) {
    left_norm += static_cast<long double>(value) * value;
    if (const auto it = right.find(key); it != right.end())
      dot += static_cast<long double>(value) * it->second;
  }
  for (const auto& [_, value] : right)
    right_norm += static_cast<long double>(value) * value;
  if (left_norm == 0.0L && right_norm == 0.0L) return 0.0;
  if (left_norm == 0.0L || right_norm == 0.0L) return 1.0;
  const double result = 1.0 - static_cast<double>(dot / std::sqrt(left_norm * right_norm));
  return std::clamp(result, 0.0, 1.0);
}

double relative(double left, double right) {
  return std::abs(left - right) / std::max({std::abs(left), std::abs(right), 1e-12});
}

double log_ratio(double left, double right, double octave_cap = 3.0) {
  if (left <= 1e-15 && right <= 1e-15) return 0.0;
  if (left <= 1e-15 || right <= 1e-15) return 1.0;
  return std::min(1.0, std::abs(std::log2(left / right)) / octave_cap);
}

double histogram_l1(const std::vector<double>& left, const std::vector<double>& right) {
  if (left.size() != right.size()) throw std::invalid_argument("histogram sizes differ");
  double sum = 0.0;
  for (std::size_t i = 0; i < left.size(); ++i) sum += std::abs(left[i] - right[i]);
  return std::min(1.0, sum / 2.0);
}

std::vector<std::uint64_t> row_token(const std::vector<double>& row) {
  std::vector<std::uint64_t> input;
  input.reserve(row.size());
  for (double value : row) {
    input.push_back(std::bit_cast<std::uint64_t>(value));
  }
  return input;
}

struct Candidate {
  double distance;
  std::vector<int> signature;
  int left;
  int right;
};
struct CandidateGreater {
  bool operator()(const Candidate& a, const Candidate& b) const {
    return std::tie(a.distance, a.signature, a.left, a.right) >
           std::tie(b.distance, b.signature, b.left, b.right);
  }
};

}  // namespace

double DistanceBreakdown::similarity() const { return std::max(0.0, 1.0 - total); }

DistanceBreakdown compare(const PartFeatures& left, const PartFeatures& right,
                          Mode mode, double strict_size_tolerance) {
  const auto& left_wl = mode == Mode::family ? left.graph.wl_family_histogram : left.graph.wl_histogram;
  const auto& right_wl = mode == Mode::family ? right.graph.wl_family_histogram : right.graph.wl_histogram;
  const double topology = cosine_distance(left_wl, right_wl);

  std::set<std::string> count_keys;
  for (const auto& [key, _] : left.graph.counts) count_keys.insert(key);
  for (const auto& [key, _] : right.graph.counts) count_keys.insert(key);
  double count_distance = 0.0;
  for (const auto& key : count_keys) {
    const double a = left.graph.counts.contains(key) ? left.graph.counts.at(key) : 0;
    const double b = right.graph.counts.contains(key) ? right.graph.counts.at(key) : 0;
    count_distance += relative(a, b);
  }
  count_distance /= std::max<std::size_t>(1, count_keys.size());
  const double surface_distance = cosine_distance(left.graph.surface_histogram, right.graph.surface_histogram);
  const double curve_distance = cosine_distance(left.graph.curve_histogram, right.graph.curve_histogram);

  const double left_scale = std::cbrt(std::max(left.exact.volume, 1e-15));
  const double right_scale = std::cbrt(std::max(right.exact.volume, 1e-15));
  std::vector<double> dimensionless{
      relative(left.exact.area / (left_scale * left_scale), right.exact.area / (right_scale * right_scale)),
      relative(left.exact.edge_length / left_scale, right.exact.edge_length / right_scale)};
  double left_moment_sum = 0.0, right_moment_sum = 0.0;
  for (double value : left.exact.moments) left_moment_sum += value;
  for (double value : right.exact.moments) right_moment_sum += value;
  if (left_moment_sum == 0.0) left_moment_sum = 1.0;
  if (right_moment_sum == 0.0) right_moment_sum = 1.0;
  for (int i = 0; i < 3; ++i)
    dimensionless.push_back(relative(left.exact.moments[i] / left_moment_sum,
                                     right.exact.moments[i] / right_moment_sum));
  double dimensionless_mean = 0.0;
  for (double value : dimensionless) dimensionless_mean += value;
  dimensionless_mean /= dimensionless.size();
  const double geometry = std::min(1.0, 0.30 * count_distance + 0.30 * surface_distance +
                                            0.15 * curve_distance + 0.25 * dimensionless_mean);
  const double shape = histogram_l1(left.graph.distance_histogram, right.graph.distance_histogram);
  const double size = (log_ratio(left.exact.volume, right.exact.volume) +
                       log_ratio(left.exact.area, right.exact.area) +
                       log_ratio(left.exact.edge_length, right.exact.edge_length)) / 3.0;
  const double size_relative = std::max({relative(left.exact.volume, right.exact.volume),
                                         relative(left.exact.area, right.exact.area),
                                         relative(left.exact.edge_length, right.exact.edge_length)});
  double total;
  if (mode == Mode::family) total = 0.48 * topology + 0.32 * geometry + 0.20 * shape;
  else total = 0.40 * topology + 0.25 * geometry + 0.20 * shape + 0.15 * size;
  const bool size_gate_failed = mode == Mode::strict && size_relative > strict_size_tolerance;
  if (size_gate_failed) total = 1.0;
  return {total, topology, geometry, shape, size, size_gate_failed};
}

std::vector<std::vector<double>> distance_matrix(const std::vector<PartFeatures>& parts,
                                                  Mode mode,
                                                  double strict_size_tolerance) {
  std::vector matrix(parts.size(), std::vector<double>(parts.size(), 0.0));
  for (std::size_t right = 0; right < parts.size(); ++right)
    for (std::size_t left = 0; left < right; ++left)
      matrix[left][right] = matrix[right][left] =
          compare(parts[left], parts[right], mode, strict_size_tolerance).total;
  return matrix;
}

std::vector<int> density_complete_link(const std::vector<std::vector<double>>& matrix,
                                       double threshold,
                                       const std::vector<std::string>& supplied_keys) {
  const int count = static_cast<int>(matrix.size());
  for (const auto& row : matrix)
    if (static_cast<int>(row.size()) != count) throw std::invalid_argument("matrix must be square");
  std::vector<std::string> keys = supplied_keys;
  if (keys.empty()) {
    keys.reserve(count);
    for (int i = 0; i < count; ++i) {
      char buffer[32];
      std::snprintf(buffer, sizeof(buffer), "%012d", i);
      keys.emplace_back(buffer);
    }
  }
  if (static_cast<int>(keys.size()) != count) throw std::invalid_argument("stable_keys length mismatch");

  std::vector<std::pair<std::string, std::vector<std::uint64_t>>> tokens;
  for (int i = 0; i < count; ++i) {
    auto sorted_row = matrix[i];
    std::sort(sorted_row.begin(), sorted_row.end());
    tokens.emplace_back(keys[i], row_token(sorted_row));
  }
  auto unique_tokens = tokens;
  std::sort(unique_tokens.begin(), unique_tokens.end());
  unique_tokens.erase(std::unique(unique_tokens.begin(), unique_tokens.end()), unique_tokens.end());
  std::vector<int> ranks(count);
  for (int i = 0; i < count; ++i)
    ranks[i] = static_cast<int>(std::lower_bound(unique_tokens.begin(), unique_tokens.end(), tokens[i]) - unique_tokens.begin());

  std::map<int, std::vector<int>> groups;
  std::map<int, std::map<int, double>> neighbors;
  std::priority_queue<Candidate, std::vector<Candidate>, CandidateGreater> heap;
  for (int i = 0; i < count; ++i) { groups[i] = {i}; neighbors[i] = {}; }
  const auto signature = [&](const std::vector<int>& a, const std::vector<int>& b) {
    std::vector<int> result;
    result.reserve(a.size() + b.size());
    for (int value : a) result.push_back(ranks[value]);
    for (int value : b) result.push_back(ranks[value]);
    std::sort(result.begin(), result.end());
    return result;
  };
  for (int left = 0; left < count; ++left) {
    for (int right = 0; right < left; ++right) {
      const double value = matrix[left][right];
      if (value <= threshold) {
        neighbors[left][right] = neighbors[right][left] = value;
        heap.push({value, signature(groups[left], groups[right]), right, left});
      }
    }
  }
  int next_group = count;
  while (!heap.empty()) {
    Candidate candidate = heap.top(); heap.pop();
    if (!groups.contains(candidate.left) || !groups.contains(candidate.right)) continue;
    const auto found = neighbors[candidate.left].find(candidate.right);
    if (found == neighbors[candidate.left].end() || found->second != candidate.distance) continue;
    const auto left_members = groups[candidate.left];
    const auto right_members = groups[candidate.right];
    const auto left_neighbors = neighbors[candidate.left];
    const auto right_neighbors = neighbors[candidate.right];
    std::vector<int> common;
    for (const auto& [other, _] : left_neighbors)
      if (other != candidate.left && other != candidate.right && right_neighbors.contains(other)) common.push_back(other);
    std::set<int> all_neighbors;
    for (const auto& [other, _] : left_neighbors) all_neighbors.insert(other);
    for (const auto& [other, _] : right_neighbors) all_neighbors.insert(other);
    for (int other : all_neighbors) {
      if (neighbors.contains(other)) { neighbors[other].erase(candidate.left); neighbors[other].erase(candidate.right); }
    }
    groups.erase(candidate.left); groups.erase(candidate.right);
    neighbors.erase(candidate.left); neighbors.erase(candidate.right);
    std::vector<int> merged = left_members;
    merged.insert(merged.end(), right_members.begin(), right_members.end());
    std::sort(merged.begin(), merged.end());
    const int merged_id = next_group++;
    groups[merged_id] = merged;
    neighbors[merged_id] = {};
    for (int other : common) {
      const double value = std::max(left_neighbors.at(other), right_neighbors.at(other));
      neighbors[merged_id][other] = neighbors[other][merged_id] = value;
      const int first = std::min(merged_id, other), second = std::max(merged_id, other);
      heap.push({value, signature(merged, groups[other]), first, second});
    }
  }
  std::vector<std::vector<int>> ordered;
  for (const auto& [_, members] : groups) ordered.push_back(members);
  std::sort(ordered.begin(), ordered.end(), [](const auto& a, const auto& b) { return a.front() < b.front(); });
  std::vector<int> assignments(count, 0);
  for (int group = 0; group < static_cast<int>(ordered.size()); ++group)
    for (int index : ordered[group]) assignments[index] = group + 1;
  return assignments;
}

void verify_assignments(const std::vector<std::vector<double>>& matrix,
                        const std::vector<int>& assignments, double threshold) {
  if (matrix.size() != assignments.size()) throw std::invalid_argument("assignment length mismatch");
  for (std::size_t right = 0; right < matrix.size(); ++right)
    for (std::size_t left = 0; left < right; ++left)
      if (assignments[left] == assignments[right] && matrix[left][right] > threshold + 1e-12)
        throw std::runtime_error("complete-link invariant failed");
}

GroupingResult group(const std::vector<PartFeatures>& parts, const Config& config) {
  auto matrix = distance_matrix(parts, config.mode, config.strict_size_tolerance);
  std::vector<std::string> stable_keys;
  stable_keys.reserve(parts.size());
  for (const auto& part : parts) {
    if (!part.source_file.empty()) stable_keys.push_back(part.source_file);
    else if (!part.label.empty()) stable_keys.push_back(part.label);
    else stable_keys.push_back(std::to_string(part.index));
  }
  auto assignments = density_complete_link(matrix, config.threshold, stable_keys);
  verify_assignments(matrix, assignments, config.threshold);
  return {std::move(assignments), std::move(matrix)};
}

}  // namespace mbd::fast
