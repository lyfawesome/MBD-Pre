#include "mbd_occt_fast/classifier.hpp"
#include "mbd_occt_fast/features.hpp"
#include <mbd_fast/topology.hpp>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepGProp.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GProp_PrincipalProps.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Circ.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Elips.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <stdexcept>

namespace mbd::occt_fast {
namespace {

fast::GeometryLabel surface_label(const TopoDS_Face& face) {
  BRepAdaptor_Surface s(face, false);
  switch (s.GetType()) {
    case GeomAbs_Plane: return {"PLANE", {}, {}};
    case GeomAbs_Cylinder: return {"CYLINDRICAL_SURFACE", {s.Cylinder().Radius()}, {}};
    // STEP uses a positive semi-angle and reverses the cone axis as needed.
    case GeomAbs_Cone: return {"CONICAL_SURFACE", {s.Cone().RefRadius()}, {std::abs(s.Cone().SemiAngle())}};
    case GeomAbs_Sphere: return {"SPHERICAL_SURFACE", {s.Sphere().Radius()}, {}};
    case GeomAbs_Torus: return {"TOROIDAL_SURFACE", {s.Torus().MajorRadius(),s.Torus().MinorRadius()}, {}};
    case GeomAbs_BSplineSurface: return {"B_SPLINE_SURFACE_WITH_KNOTS", {}, {}};
    case GeomAbs_BezierSurface: return {"B_SPLINE_SURFACE_WITH_KNOTS", {}, {}};
    case GeomAbs_SurfaceOfRevolution: return {"SURFACE_OF_REVOLUTION", {}, {}};
    case GeomAbs_SurfaceOfExtrusion: return {"SURFACE_OF_LINEAR_EXTRUSION", {}, {}};
    case GeomAbs_OffsetSurface: return {"OFFSET_SURFACE", {s.OffsetValue()}, {}};
    default: throw std::invalid_argument("unsupported surface type");
  }
}

fast::GeometryLabel curve_label(const TopoDS_Edge& edge) {
  BRepAdaptor_Curve c(edge);
  switch (c.GetType()) {
    case GeomAbs_Line: return {"LINE", {}, {}};
    case GeomAbs_Circle: return {"CIRCLE", {c.Circle().Radius()}, {}};
    case GeomAbs_Ellipse: return {"ELLIPSE", {c.Ellipse().MajorRadius(),c.Ellipse().MinorRadius()}, {}};
    case GeomAbs_BSplineCurve: return {"B_SPLINE_CURVE_WITH_KNOTS", {}, {}};
    case GeomAbs_BezierCurve: return {"B_SPLINE_CURVE_WITH_KNOTS", {}, {}};
    default: throw std::invalid_argument("unsupported edge curve type");
  }
}

void require_solid(const TopoDS_Shape& shape) {
  if (shape.IsNull() || !TopExp_Explorer(shape, TopAbs_SOLID).More())
    throw std::invalid_argument("shape contains no solid");
  if (shape.ShapeType() == TopAbs_SOLID) return;
  // Mixed solids and loose faces/edges would give mass properties and topology
  // different meanings. Require a body to be a solid or a solid assembly.
  if (shape.ShapeType() != TopAbs_COMPOUND && shape.ShapeType() != TopAbs_COMPSOLID)
    throw std::invalid_argument("expected a solid or solid assembly");
  for (TopoDS_Iterator child(shape); child.More(); child.Next())
    require_solid(child.Value());
}

// A wire consisting only of a path followed in reverse has no geometric
// boundary (e.g. a complete sphere's meridian). The STEP baseline represents
// it as a vertex loop. Detect that topology directly without serializing.
TopoDS_Vertex vertex_loop(const std::vector<TopoDS_Edge>& uses) {
  if (uses.empty() || uses.size()%2) return {};
  const auto n=uses.size();
  for (std::size_t start=0;start<n;++start) {
    bool retraced=true;
    for (std::size_t i=0;i<n/2;++i)
      retraced=retraced&&uses[(start+i)%n].IsSame(uses[(start+n-1-i)%n]);
    if (retraced) return TopExp::FirstVertex(uses[start],true);
  }
  return {};
}

fast::PartTopology topology_of(const TopoDS_Shape& shape) {
  fast::PartTopology result;
  // Match STEP's topological identity, not geometric equality: coincident
  // vertices may be distinct topology; coordinate dedup happens in the kernel.
  // Maps are per solid occurrence so compound copies remain whole logical parts.
  for (TopExp_Explorer solids(shape, TopAbs_SOLID); solids.More(); solids.Next()) {
    TopTools_IndexedMapOfShape edges, vertices;
    const int edge_offset = static_cast<int>(result.edges.size());
    for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
      const auto face = TopoDS::Face(faces.Current().Oriented(TopAbs_FORWARD));
      fast::FaceTopology f;
      f.surface = surface_label(face);
      for (TopExp_Explorer wires(face, TopAbs_WIRE); wires.More(); wires.Next()) {
        ++f.bounds;
        ++result.counts["FACE_BOUND"];
        std::vector<TopoDS_Edge> uses;
        const auto wire=TopoDS::Wire(wires.Current().Oriented(TopAbs_FORWARD));
        for (BRepTools_WireExplorer walker(wire,face);walker.More();walker.Next())
          if (!BRep_Tool::Degenerated(walker.Current())) uses.push_back(walker.Current());
        std::size_t expected_uses = 0;
        for (TopExp_Explorer edges(wire, TopAbs_EDGE); edges.More(); edges.Next())
          if (!BRep_Tool::Degenerated(TopoDS::Edge(edges.Current()))) ++expected_uses;
        if (uses.size() != expected_uses)
          throw std::invalid_argument("wire traversal is incomplete");
        const auto pole=vertex_loop(uses);
        if (!pole.IsNull()) {
          vertices.Add(pole);
          continue;
        }
        if (uses.empty()) throw std::invalid_argument("wire has no usable edges");
        ++result.counts["EDGE_LOOP"];
        for (const auto& edge:uses) {
          const int count_before = edges.Extent();
          const int id = edges.Add(edge);
          if (edges.Extent() != count_before) result.edges.push_back(curve_label(edge));
          f.edge_uses.push_back(edge_offset + id - 1);
          ++result.counts["ORIENTED_EDGE"];
          TopExp::MapShapes(edge, TopAbs_VERTEX, vertices);
        }
      }
      result.faces.push_back(std::move(f));
      ++result.counts["ADVANCED_FACE"];
    }
    result.counts["EDGE_CURVE"] += edges.Extent();
    result.counts["VERTEX_POINT"] += vertices.Extent();
    for (int i=1;i<=vertices.Extent();++i) {
      const auto point = BRep_Tool::Pnt(TopoDS::Vertex(vertices(i)));
      result.vertices.push_back({point.X(),point.Y(),point.Z()});
    }
    for (TopExp_Explorer shells(solids.Current(), TopAbs_SHELL); shells.More(); shells.Next())
      ++result.counts["CLOSED_SHELL"];
  }
  return result;
}

} // namespace

fast::ExactProperties exact_properties(const TopoDS_Shape& shape, int index) {
  require_solid(shape);
  GProp_GProps volume, surface, linear;
  BRepGProp::VolumeProperties(shape, volume, 1e-9, false, false);
  BRepGProp::SurfaceProperties(shape, surface, 1e-9, false);
  BRepGProp::LinearProperties(shape, linear, true, false);
  std::array<double,3> moments{};
  volume.PrincipalProperties().Moments(moments[0],moments[1],moments[2]);
  std::sort(moments.begin(),moments.end(),std::greater<>());
  // Preserve Python DRAW lprops -full's closed-solid edge-use convention.
  fast::ExactProperties result{index,volume.Mass(),surface.Mass(),2.0*linear.Mass(),moments};
  if (!std::isfinite(result.volume) || result.volume <= 0 ||
      !std::isfinite(result.area) || result.area <= 0 ||
      !std::isfinite(result.edge_length) || result.edge_length < 0)
    throw std::invalid_argument("invalid solid mass properties");
  for (double m : moments)
    if (!std::isfinite(m) || m < 0) throw std::invalid_argument("invalid inertia");
  return result;
}

fast::PartFeatures describe(const TopoDS_Shape& shape, int iterations) {
  auto exact = exact_properties(shape);
  auto graph = fast::describe_topology(topology_of(shape),iterations,
                                      std::cbrt(std::max(exact.volume,1e-15)));
  return {0,{},exact,std::move(graph),{}};
}

Result classify(const std::vector<Body>& bodies, const Options& options) {
  if ((options.mode != Mode::strict && options.mode != Mode::family) ||
      !std::isfinite(options.threshold) || options.threshold < 0 || options.threshold > 1 ||
      !std::isfinite(options.size_tolerance) || options.size_tolerance < 0 ||
      options.wl_iterations < 0)
    throw std::invalid_argument("invalid classification options");
  std::map<std::string,const Body*> ordered;
  for (const auto& body : bodies)
    if (body.id.empty() || !ordered.emplace(body.id,&body).second)
      throw std::invalid_argument("body IDs must be nonempty and unique");
  Result result;
  std::vector<fast::PartFeatures> features;
  for (const auto& [id,body] : ordered) {
    try {
      auto part = describe(body->shape, options.wl_iterations);
      part.source_file = id; // Stable identity only; never interpreted as a path.
      features.push_back(std::move(part));
      result.body_ids.push_back(id);
    } catch (const Standard_Failure& error) {
      result.skipped.push_back({id,error.GetMessageString()?error.GetMessageString():"OCCT failure"});
    } catch (const std::invalid_argument& error) {
      result.skipped.push_back({id,error.what()});
    }
  }
  fast::Config config;
  config.mode = options.mode == Mode::strict ? fast::Mode::strict : fast::Mode::family;
  config.threshold = options.threshold;
  config.strict_size_tolerance = options.size_tolerance;
  auto grouped = fast::group(features,config);
  for (std::size_t i=0;i<grouped.assignments.size();++i) {
    const auto group = static_cast<std::size_t>(grouped.assignments[i]);
    if (result.groups.size()<group) result.groups.resize(group);
    result.groups[group-1].push_back(result.body_ids[i]);
  }
  result.assignments=std::move(grouped.assignments);
  result.distances=std::move(grouped.distances);
  return result;
}

} // namespace mbd::occt_fast
