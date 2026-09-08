#include "mbd/fast.hpp"
#include "mbd/occt.hpp"
#include "mbd/rigid.hpp"
#include "mbd/step_graph.hpp"

#include <nlohmann/json.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <cmath>
#include <limits>
#include <set>
#include <stdexcept>

using json = nlohmann::json;

namespace {

std::vector<int> assignments_from_groups(const json& groups, std::size_t count) {
  std::vector<int> result(count, 0);
  for (const auto& group : groups)
    for (int part : group.at("parts").get<std::vector<int>>()) result.at(part - 1) = group.at("group").get<int>();
  return result;
}

json groups_json(const std::vector<int>& assignments) {
  std::map<int, std::vector<int>> groups;
  for (std::size_t index = 0; index < assignments.size(); ++index)
    groups[assignments[index]].push_back(static_cast<int>(index + 1));
  json result = json::array();
  for (const auto& [group, parts] : groups)
    result.push_back({{"group", group}, {"part_count", parts.size()}, {"parts", parts}});
  return result;
}

json descriptor_json(const mbd::GraphDescriptor& graph) {
  return {{"counts", graph.counts}, {"surface_histogram", graph.surface_histogram},
          {"curve_histogram", graph.curve_histogram}, {"wl_histogram", graph.wl_histogram},
          {"wl_family_histogram", graph.wl_family_histogram},
          {"distance_histogram", graph.distance_histogram}, {"graph", graph.graph}};
}

bool same_partition(const std::vector<int>& left, const std::vector<int>& right) {
  if (left.size() != right.size()) return false;
  for (std::size_t a = 0; a < left.size(); ++a)
    for (std::size_t b = 0; b < a; ++b)
      if ((left[a] == left[b]) != (right[a] == right[b])) return false;
  return true;
}

mbd::PartFeatures part_from_json(const json& row) {
  mbd::PartFeatures result;
  result.index = row.at("part_index").get<int>();
  result.label = row.value("name", "");
  const auto& exact = row.at("exact");
  result.exact.index = result.index;
  result.exact.volume = exact.at("volume").get<double>();
  result.exact.area = exact.at("area").get<double>();
  result.exact.edge_length = exact.at("edge_length").get<double>();
  result.exact.moments = exact.at("moments").get<std::array<double, 3>>();
  const auto& descriptor = row.at("descriptor");
  result.graph.counts = descriptor.at("counts").get<std::map<std::string, int>>();
  result.graph.surface_histogram = descriptor.at("surface_histogram").get<std::map<std::string, int>>();
  result.graph.curve_histogram = descriptor.at("curve_histogram").get<std::map<std::string, int>>();
  result.graph.wl_histogram = descriptor.at("wl_histogram").get<std::map<std::string, int>>();
  result.graph.wl_family_histogram = descriptor.at("wl_family_histogram").get<std::map<std::string, int>>();
  result.graph.distance_histogram = descriptor.at("distance_histogram").get<std::vector<double>>();
  if (descriptor.contains("graph"))
    result.graph.graph = descriptor.at("graph").get<std::map<std::string, int>>();
  return result;
}

int parity_report(const std::filesystem::path& report_path,
                  const std::filesystem::path& normalized_dir) {
  std::ifstream input(report_path);
  if (!input) throw std::runtime_error("cannot open report: " + report_path.string());
  json report; input >> report;
  std::vector<mbd::PartFeatures> parts;
  bool descriptor_equal = true;
  double descriptor_histogram_max_error = 0.0;
  std::size_t count_mismatches = 0, surface_mismatches = 0, curve_mismatches = 0;
  std::size_t wl_mismatches = 0, family_wl_mismatches = 0;
  std::size_t graph_mismatches = 0;
  std::vector<int> wl_mismatch_parts, family_wl_mismatch_parts;
  for (const auto& row : report.at("parts")) {
    auto part = part_from_json(row);
    char filename[32];
    std::snprintf(filename, sizeof(filename), "part_%04d.step", part.index);
    auto [_, descriptor] = mbd::describe_normalized_step(
        (normalized_dir / filename).string(), 3, std::cbrt(std::max(part.exact.volume, 1e-15)));
    count_mismatches += descriptor.counts != part.graph.counts;
    surface_mismatches += descriptor.surface_histogram != part.graph.surface_histogram;
    curve_mismatches += descriptor.curve_histogram != part.graph.curve_histogram;
    if (descriptor.wl_histogram != part.graph.wl_histogram) { ++wl_mismatches; wl_mismatch_parts.push_back(part.index); }
    if (descriptor.wl_family_histogram != part.graph.wl_family_histogram) {
      ++family_wl_mismatches; family_wl_mismatch_parts.push_back(part.index);
    }
    graph_mismatches += descriptor.graph != part.graph.graph;
    descriptor_equal = descriptor_equal && descriptor.distance_histogram.size() == part.graph.distance_histogram.size();
    if (descriptor.distance_histogram.size() == part.graph.distance_histogram.size())
      for (std::size_t i = 0; i < descriptor.distance_histogram.size(); ++i)
        descriptor_histogram_max_error = std::max(
            descriptor_histogram_max_error,
            std::abs(descriptor.distance_histogram[i] - part.graph.distance_histogram[i]));
    part.graph = std::move(descriptor);
    parts.push_back(std::move(part));
  }
  descriptor_equal = descriptor_equal && count_mismatches == 0 && surface_mismatches == 0 &&
      curve_mismatches == 0 && wl_mismatches == 0 && family_wl_mismatches == 0 &&
      graph_mismatches == 0 &&
      descriptor_histogram_max_error <= 1e-10;
  const std::string mode = report.at("config").value("mode", "strict");
  const double size_tolerance = report.at("config").value("size_tolerance", 0.03);
  const double threshold = report.at("config").value("threshold", 0.12);
  const double vertex_tolerance = report.at("config").value("vertex_tolerance", 1e-5);
  const auto matrix = mbd::distance_matrix(parts, mode, size_tolerance);
  double distance_matrix_max_error = 0.0;
  if (report.contains("parity_distance_matrix")) {
    const auto expected = report.at("parity_distance_matrix").get<std::vector<std::vector<double>>>();
    if (expected.size() != matrix.size()) distance_matrix_max_error = std::numeric_limits<double>::infinity();
    else for (std::size_t i = 0; i < matrix.size(); ++i) {
      if (expected[i].size() != matrix[i].size()) {
        distance_matrix_max_error = std::numeric_limits<double>::infinity();
        break;
      }
      for (std::size_t j = 0; j < matrix[i].size(); ++j)
        distance_matrix_max_error = std::max(
            distance_matrix_max_error, std::abs(matrix[i][j] - expected[i][j]));
    }
  }
  std::vector<std::string> stable_keys;
  for (const auto& part : parts) stable_keys.push_back(std::to_string(part.index));
  const auto fast = mbd::density_complete_link(matrix, threshold, stable_keys);
  mbd::verify_assignments(matrix, fast, threshold);
  const auto expected_fast = assignments_from_groups(report.at("candidate_groups"), parts.size());

  std::vector<mbd::RigidGeometry> geometries;
  geometries.reserve(parts.size());
  for (std::size_t i = 0; i < parts.size(); ++i) {
    char filename[32];
    std::snprintf(filename, sizeof(filename), "part_%04zu.step", i + 1);
    geometries.push_back(mbd::load_rigid_geometry((normalized_dir / filename).string()));
  }
  const auto rigid = mbd::refine_candidate_groups_rigid(fast, geometries, vertex_tolerance);
  const auto expected_rigid = assignments_from_groups(report.at("groups"), parts.size());
  const bool fast_equal = same_partition(fast, expected_fast);
  const bool rigid_equal = same_partition(rigid, expected_rigid);
  json output{
      {"part_count", parts.size()},
      {"fast_group_count", std::set<int>(fast.begin(), fast.end()).size()},
      {"rigid_group_count", std::set<int>(rigid.begin(), rigid.end()).size()},
      {"descriptor_equal", descriptor_equal},
      {"descriptor_histogram_max_error", descriptor_histogram_max_error},
      {"distance_matrix_checked", report.contains("parity_distance_matrix")},
      {"distance_matrix_max_error", report.contains("parity_distance_matrix") ? json(distance_matrix_max_error) : json(nullptr)},
      {"descriptor_map_mismatches", {{"counts", count_mismatches},
          {"surfaces", surface_mismatches}, {"curves", curve_mismatches},
          {"wl", wl_mismatches}, {"family_wl", family_wl_mismatches},
          {"graph", graph_mismatches}}},
      {"wl_mismatch_parts", wl_mismatch_parts},
      {"family_wl_mismatch_parts", family_wl_mismatch_parts},
      {"fast_partition_equal", fast_equal},
      {"rigid_partition_equal", rigid_equal},
      {"fast_assignments", fast},
      {"rigid_assignments", rigid}};
  std::cout << output.dump(2) << '\n';
  return descriptor_equal && distance_matrix_max_error <= 1e-12 && fast_equal && rigid_equal ? 0 : 2;
}

int run_source(const std::filesystem::path& source, const std::filesystem::path& output,
               const std::string& precision_mode) {
  if (precision_mode != "off" && precision_mode != "rigid")
    throw std::invalid_argument("C++ precision mode must be off or rigid");
  const auto normalized = output / "normalized_parts";
  const auto exact = mbd::inspect_and_normalize(source, normalized);
  std::vector<mbd::PartFeatures> parts;
  json part_rows = json::array();
  for (const auto& properties : exact) {
    char filename[32];
    std::snprintf(filename, sizeof(filename), "part_%04d.step", properties.index);
    auto [label, descriptor] = mbd::describe_normalized_step(
        (normalized / filename).string(), 3, std::cbrt(std::max(properties.volume, 1e-15)));
    parts.push_back({properties.index, label, properties, descriptor, filename});
    part_rows.push_back({{"part_index", properties.index}, {"name", label},
        {"exact", {{"volume", properties.volume}, {"area", properties.area},
                    {"edge_length", properties.edge_length}, {"moments", properties.moments}}},
        {"descriptor", descriptor_json(descriptor)}});
  }
  const auto matrix = mbd::distance_matrix(parts, "strict", 0.03);
  std::vector<std::string> keys;
  for (const auto& part : parts) keys.push_back(std::to_string(part.index));
  const auto fast = mbd::density_complete_link(matrix, 0.12, keys);
  mbd::verify_assignments(matrix, fast, 0.12);
  std::vector<int> final = fast;
  if (precision_mode == "rigid") {
    std::vector<mbd::RigidGeometry> geometries;
    for (std::size_t index = 0; index < parts.size(); ++index) {
      char filename[32];
      std::snprintf(filename, sizeof(filename), "part_%04zu.step", index + 1);
      geometries.push_back(mbd::load_rigid_geometry((normalized / filename).string()));
    }
    final = mbd::refine_candidate_groups_rigid(fast, geometries, 1e-5);
  }
  json report{{"version", "cpp-0.1.0"}, {"source", std::filesystem::absolute(source).string()},
      {"config", {{"mode", "strict"}, {"threshold", 0.12}, {"size_tolerance", 0.03},
                   {"wl_iterations", 3}, {"precision_mode", precision_mode},
                   {"vertex_tolerance", 1e-5}}},
      {"part_count", parts.size()}, {"candidate_group_count", std::set<int>(fast.begin(), fast.end()).size()},
      {"group_count", std::set<int>(final.begin(), final.end()).size()},
      {"candidate_groups", groups_json(fast)}, {"groups", groups_json(final)}, {"parts", part_rows}};
  std::filesystem::create_directories(output);
  std::ofstream file(output / "report.json");
  file << report.dump(2) << '\n';
  std::cout << json{{"part_count", parts.size()},
      {"candidate_group_count", report["candidate_group_count"]},
      {"group_count", report["group_count"]},
      {"report", std::filesystem::absolute(output / "report.json").string()}}.dump(2) << '\n';
  return 0;
}

void usage() {
  std::cerr << "usage: mbd_geometry_cli parity-report <report.json> <normalized_parts>\n"
               "       mbd_geometry_cli run <assembly.step> <output> <off|rigid>\n"
               "       mbd_geometry_cli descriptor <part.step> <part-scale>\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc == 4 && std::string(argv[1]) == "parity-report")
      return parity_report(argv[2], argv[3]);
    if (argc == 5 && std::string(argv[1]) == "run")
      return run_source(argv[2], argv[3], argv[4]);
    if (argc == 4 && std::string(argv[1]) == "descriptor") {
      const auto [label, graph] = mbd::describe_normalized_step(argv[2], 3, std::stod(argv[3]));
      std::cout << json{{"label", label}, {"counts", graph.counts},
          {"surface_histogram", graph.surface_histogram}, {"curve_histogram", graph.curve_histogram},
          {"wl_histogram", graph.wl_histogram}, {"wl_family_histogram", graph.wl_family_histogram},
          {"distance_histogram", graph.distance_histogram}, {"graph", graph.graph}}.dump(2) << '\n';
      return 0;
    }
    usage(); return 64;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
