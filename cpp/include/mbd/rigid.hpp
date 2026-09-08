#pragma once

#include <array>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace mbd {

using Point = std::array<double, 3>;
using Matrix3 = std::array<std::array<double, 3>, 3>;
using EdgeKey = std::tuple<int, int, std::string>;
using EdgeSignature = std::map<EdgeKey, int>;

struct FaceKey {
  std::string surface;
  std::vector<EdgeKey> boundary;
  auto operator<=>(const FaceKey&) const = default;
};
using FaceSignature = std::map<FaceKey, int>;

struct RigidGeometry {
  std::vector<Point> points;
  EdgeSignature edges;
  FaceSignature faces;
};

struct RigidTransform {
  Matrix3 rotation{};
  Point translation{};
  Point axis{};
  double angle_degrees{};
  double rms_vertex_error{};
  double max_vertex_error{};
};

RigidGeometry load_rigid_geometry(const std::string& path);

std::optional<RigidTransform> find_rigid_transform(
    const std::vector<Point>& source, const std::vector<Point>& target,
    double tolerance = 1e-5, const EdgeSignature* source_edges = nullptr,
    const EdgeSignature* target_edges = nullptr,
    const FaceSignature* source_faces = nullptr,
    const FaceSignature* target_faces = nullptr);

std::vector<int> refine_candidate_groups_rigid(
    const std::vector<int>& candidate_assignments,
    const std::vector<RigidGeometry>& geometries, double tolerance = 1e-5);

std::vector<int> full_rigid_group(const std::vector<RigidGeometry>& geometries,
                                  double tolerance = 1e-5);

}  // namespace mbd
