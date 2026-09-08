#include "mbd/rigid.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <queue>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace mbd {
namespace {

struct Entity {
  std::string kind;
  std::string body;
  std::vector<int> refs;
};
using Entities = std::map<int, Entity>;

const std::set<std::string> surface_types{
    "PLANE", "CYLINDRICAL_SURFACE", "CONICAL_SURFACE", "SPHERICAL_SURFACE",
    "TOROIDAL_SURFACE", "B_SPLINE_SURFACE_WITH_KNOTS", "BEZIER_SURFACE",
    "SURFACE_OF_REVOLUTION", "SURFACE_OF_LINEAR_EXTRUSION", "OFFSET_SURFACE"};
const std::set<std::string> curve_types{
    "LINE", "CIRCLE", "ELLIPSE", "B_SPLINE_CURVE_WITH_KNOTS", "B_SPLINE_CURVE",
    "RATIONAL_B_SPLINE_CURVE", "BEZIER_CURVE", "SURFACE_CURVE", "PCURVE", "TRIMMED_CURVE"};
const std::set<std::string> base_curve_types{
    "LINE", "CIRCLE", "ELLIPSE", "B_SPLINE_CURVE_WITH_KNOTS", "B_SPLINE_CURVE",
    "RATIONAL_B_SPLINE_CURVE", "BEZIER_CURVE"};
const std::set<std::string> solid_types{"MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "FACETED_BREP"};

std::string read_file(const std::string& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot open STEP file: " + path);
  std::ostringstream stream;
  stream << input.rdbuf();
  return stream.str();
}

std::vector<int> find_refs(const std::string& body) {
  static const std::regex pattern(R"(#(\d+))");
  std::vector<int> result;
  for (std::sregex_iterator it(body.begin(), body.end(), pattern), end; it != end; ++it)
    result.push_back(std::stoi((*it)[1].str()));
  return result;
}

Entities parse_step(const std::string& path) {
  const std::string text = read_file(path);
  static const std::regex simple(R"(^\s*([A-Z][A-Z0-9_]*)\s*\(([\s\S]*)\)\s*$)");
  static const std::regex kind_pattern(R"(([A-Z][A-Z0-9_]*)\s*\()");
  const std::vector<std::string> priority{
      "B_SPLINE_CURVE_WITH_KNOTS", "RATIONAL_B_SPLINE_CURVE", "B_SPLINE_CURVE",
      "B_SPLINE_SURFACE_WITH_KNOTS", "RATIONAL_B_SPLINE_SURFACE", "B_SPLINE_SURFACE"};
  Entities entities;
  std::size_t position = 0;
  while ((position = text.find('#', position)) != std::string::npos) {
    std::size_t cursor = position + 1;
    while (cursor < text.size() && std::isdigit(static_cast<unsigned char>(text[cursor]))) ++cursor;
    if (cursor == position + 1) { ++position; continue; }
    const int id = std::stoi(text.substr(position + 1, cursor - position - 1));
    while (cursor < text.size() && std::isspace(static_cast<unsigned char>(text[cursor]))) ++cursor;
    if (cursor >= text.size() || text[cursor] != '=') { position = cursor; continue; }
    const std::size_t value_begin = ++cursor;
    bool quoted = false;
    while (cursor < text.size()) {
      if (text[cursor] == '\'') {
        if (quoted && cursor + 1 < text.size() && text[cursor + 1] == '\'') { cursor += 2; continue; }
        quoted = !quoted;
      }
      if (!quoted && text[cursor] == ';') break;
      ++cursor;
    }
    if (cursor >= text.size()) break;
    std::string value = text.substr(value_begin, cursor - value_begin);
    const auto first = value.find_first_not_of(" \t\r\n");
    const auto last = value.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) { position = cursor + 1; continue; }
    value = value.substr(first, last - first + 1);
    std::smatch match;
    std::string kind, body;
    if (std::regex_match(value, match, simple)) {
      kind = match[1].str(); body = match[2].str();
    } else {
      std::vector<std::string> kinds;
      for (std::sregex_iterator it(value.begin(), value.end(), kind_pattern), end; it != end; ++it)
        kinds.push_back((*it)[1].str());
      if (kinds.empty()) { position = cursor + 1; continue; }
      kind = kinds.front();
      for (const auto& preferred : priority)
        if (std::find(kinds.begin(), kinds.end(), preferred) != kinds.end()) { kind = preferred; break; }
      body = value;
    }
    entities[id] = {kind, body, find_refs(body)};
    position = cursor + 1;
  }
  if (entities.empty()) throw std::runtime_error("no STEP entities found: " + path);
  return entities;
}

std::string entity_kind(int ref, const Entities& entities) {
  const auto it = entities.find(ref);
  return it == entities.end() ? "" : it->second.kind;
}

int solid_root(const Entities& entities) {
  for (const auto& [id, entity] : entities) if (solid_types.contains(entity.kind)) return id;
  throw std::runtime_error("normalized STEP contains no supported solid");
}

std::set<int> reachable(int root, const Entities& entities) {
  std::set<int> seen;
  std::vector<int> stack{root};
  while (!stack.empty()) {
    const int current = stack.back(); stack.pop_back();
    if (seen.contains(current) || !entities.contains(current)) continue;
    seen.insert(current);
    const auto& refs = entities.at(current).refs;
    stack.insert(stack.end(), refs.begin(), refs.end());
  }
  return seen;
}

std::optional<Point> cartesian_point(const Entity& entity) {
  if (entity.kind != "CARTESIAN_POINT") return std::nullopt;
  static const std::regex number(R"([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:E[-+]?\d+)?)",
                                 std::regex::icase);
  std::vector<double> values;
  for (std::sregex_iterator it(entity.body.begin(), entity.body.end(), number), end; it != end; ++it)
    values.push_back(std::stod(it->str()));
  if (values.size() < 3) return std::nullopt;
  return Point{values[values.size()-3], values[values.size()-2], values[values.size()-1]};
}

double rounded10(double value) { return std::round(value * 1e10) / 1e10; }

std::vector<Point> vertex_points(const std::set<int>& ids, const Entities& entities) {
  std::set<Point> unique;
  for (int id : ids) {
    const auto& entity = entities.at(id);
    if (entity.kind != "VERTEX_POINT") continue;
    for (int ref : entity.refs) {
      if (entity_kind(ref, entities) != "CARTESIAN_POINT") continue;
      if (auto point = cartesian_point(entities.at(ref)))
        unique.insert({rounded10((*point)[0]), rounded10((*point)[1]), rounded10((*point)[2])});
    }
  }
  return {unique.begin(), unique.end()};
}

std::optional<int> edge_curve_from_oriented(int edge_id, const Entities& entities) {
  const auto found = entities.find(edge_id);
  if (found == entities.end()) return std::nullopt;
  if (found->second.kind == "EDGE_CURVE") return edge_id;
  if (found->second.kind == "ORIENTED_EDGE") {
    for (auto it = found->second.refs.rbegin(); it != found->second.refs.rend(); ++it)
      if (entity_kind(*it, entities) == "EDGE_CURVE") return *it;
  }
  return std::nullopt;
}

std::vector<int> face_edge_curves(int face_id, const Entities& entities) {
  std::vector<int> result;
  for (int bound : entities.at(face_id).refs) {
    const std::string kind = entity_kind(bound, entities);
    if (kind != "FACE_BOUND" && kind != "FACE_OUTER_BOUND") continue;
    for (int loop : entities.at(bound).refs) {
      if (entity_kind(loop, entities) != "EDGE_LOOP") continue;
      for (int oriented : entities.at(loop).refs)
        if (auto edge = edge_curve_from_oriented(oriented, entities)) result.push_back(*edge);
    }
  }
  return result;
}

std::string surface_for_face(int face_id, const Entities& entities) {
  const auto& refs = entities.at(face_id).refs;
  for (auto it = refs.rbegin(); it != refs.rend(); ++it) {
    const std::string kind = entity_kind(*it, entities);
    if (surface_types.contains(kind) || kind.find("SURFACE") != std::string::npos) return kind;
  }
  return "UNKNOWN_SURFACE";
}

std::string curve_for_edge(int edge_id, const Entities& entities) {
  std::deque<int> queue(entities.at(edge_id).refs.begin(), entities.at(edge_id).refs.end());
  std::set<int> seen;
  std::optional<std::string> fallback;
  while (!queue.empty()) {
    const int ref = queue.front(); queue.pop_front();
    if (seen.contains(ref)) continue;
    seen.insert(ref);
    const auto found = entities.find(ref);
    if (found == entities.end()) continue;
    if (base_curve_types.contains(found->second.kind)) return found->second.kind;
    if (curve_types.contains(found->second.kind) || found->second.kind.find("CURVE") != std::string::npos) {
      if (!fallback) fallback = found->second.kind;
      queue.insert(queue.begin(), found->second.refs.begin(), found->second.refs.end());
    }
  }
  return fallback.value_or("UNKNOWN_CURVE");
}

Point sub(const Point& a, const Point& b) { return {a[0]-b[0], a[1]-b[1], a[2]-b[2]}; }
Point add(const Point& a, const Point& b) { return {a[0]+b[0], a[1]+b[1], a[2]+b[2]}; }
Point scale(const Point& a, double factor) { return {a[0]*factor, a[1]*factor, a[2]*factor}; }
double dot(const Point& a, const Point& b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
Point cross(const Point& a, const Point& b) {
  return {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
}
double norm(const Point& a) { return std::sqrt(dot(a, a)); }
double distance(const Point& a, const Point& b) { return norm(sub(a, b)); }
Point unit(const Point& a) {
  const double magnitude = norm(a);
  if (magnitude <= 1e-15) throw std::runtime_error("cannot normalize zero vector");
  return scale(a, 1.0/magnitude);
}
Matrix3 frame(const Point& a, const Point& b, const Point& c) {
  const Point first = unit(sub(b, a));
  const Point ca = sub(c, a);
  const Point second = unit(sub(ca, scale(first, dot(ca, first))));
  return {first, second, unit(cross(first, second))};
}
Matrix3 rotation(const Matrix3& source, const Matrix3& target) {
  Matrix3 result{};
  for (int row=0; row<3; ++row) for (int column=0; column<3; ++column)
    for (int k=0; k<3; ++k) result[row][column] += target[k][row] * source[k][column];
  return result;
}
Point matvec(const Matrix3& matrix, const Point& point) {
  Point result{};
  for (int row=0; row<3; ++row) for (int column=0; column<3; ++column)
    result[row] += matrix[row][column] * point[column];
  return result;
}

std::pair<Point,double> axis_angle(const Matrix3& m) {
  double qw=0,qx=0,qy=0,qz=0;
  const double trace=m[0][0]+m[1][1]+m[2][2];
  if(trace>0){const double s=std::sqrt(trace+1.0)*2;qw=.25*s;qx=(m[2][1]-m[1][2])/s;qy=(m[0][2]-m[2][0])/s;qz=(m[1][0]-m[0][1])/s;}
  else {
    int largest=0;if(m[1][1]>m[largest][largest])largest=1;if(m[2][2]>m[largest][largest])largest=2;
    if(largest==0){const double s=std::sqrt(std::max(0.0,1+m[0][0]-m[1][1]-m[2][2]))*2;qw=(m[2][1]-m[1][2])/s;qx=.25*s;qy=(m[0][1]+m[1][0])/s;qz=(m[0][2]+m[2][0])/s;}
    else if(largest==1){const double s=std::sqrt(std::max(0.0,1+m[1][1]-m[0][0]-m[2][2]))*2;qw=(m[0][2]-m[2][0])/s;qy=.25*s;qx=(m[0][1]+m[1][0])/s;qz=(m[1][2]+m[2][1])/s;}
    else{const double s=std::sqrt(std::max(0.0,1+m[2][2]-m[0][0]-m[1][1]))*2;qw=(m[1][0]-m[0][1])/s;qz=.25*s;qx=(m[0][2]+m[2][0])/s;qy=(m[1][2]+m[2][1])/s;}
  }
  const double qnorm=std::sqrt(qw*qw+qx*qx+qy*qy+qz*qz);qw/=qnorm;qx/=qnorm;qy/=qnorm;qz/=qnorm;
  if(qw<0){qw=-qw;qx=-qx;qy=-qy;qz=-qz;}
  const double vnorm=std::sqrt(qx*qx+qy*qy+qz*qz);
  if(vnorm<1e-14)return {{0,0,1},0};
  return {{qx/vnorm,qy/vnorm,qz/vnorm},2*std::atan2(vnorm,std::clamp(qw,-1.0,1.0))*180.0/std::acos(-1.0)};
}

using Fingerprint=std::vector<long long>;
std::vector<Fingerprint> fingerprints(const std::vector<Point>& points,double tolerance){
  std::vector<Fingerprint> result(points.size());
  for(std::size_t i=0;i<points.size();++i){for(std::size_t j=0;j<points.size();++j)if(i!=j)result[i].push_back(static_cast<long long>(std::nearbyint(distance(points[i],points[j])/tolerance)));std::sort(result[i].begin(),result[i].end());}
  return result;
}
bool fingerprint_compatible(const Fingerprint&a,const Fingerprint&b){if(a.size()!=b.size())return false;for(std::size_t i=0;i<a.size();++i)if(std::llabs(a[i]-b[i])>1)return false;return true;}

struct MatchResult { double rms; double maximum; std::vector<int> mapping; };
std::optional<MatchResult> match_points(const std::vector<Point>& transformed,const std::vector<Point>& target,double tolerance){
  using Bucket=std::tuple<long long,long long,long long>;std::map<Bucket,std::vector<int>> buckets;
  for(int i=0;i<static_cast<int>(target.size());++i)buckets[{static_cast<long long>(std::nearbyint(target[i][0]/tolerance)),static_cast<long long>(std::nearbyint(target[i][1]/tolerance)),static_cast<long long>(std::nearbyint(target[i][2]/tolerance))}].push_back(i);
  std::set<int> used;std::vector<double> errors;std::vector<int> mapping;
  for(const Point& point:transformed){const long long x=std::nearbyint(point[0]/tolerance),y=std::nearbyint(point[1]/tolerance),z=std::nearbyint(point[2]/tolerance);double best=std::numeric_limits<double>::infinity();int chosen=-1;for(int dx=-1;dx<=1;++dx)for(int dy=-1;dy<=1;++dy)for(int dz=-1;dz<=1;++dz){const auto it=buckets.find({x+dx,y+dy,z+dz});if(it==buckets.end())continue;for(int candidate:it->second)if(!used.contains(candidate)){const double error=distance(point,target[candidate]);if(error<best){best=error;chosen=candidate;}}}if(chosen<0||best>tolerance)return std::nullopt;used.insert(chosen);errors.push_back(best);mapping.push_back(chosen);}
  if (used.size() != target.size()) return std::nullopt;
  double squares = 0;
  for (double error : errors) squares += error * error;
  return MatchResult{std::sqrt(squares/std::max<std::size_t>(1,errors.size())),
                     errors.empty()?0:*std::max_element(errors.begin(),errors.end()), mapping};
}

std::string invariant_key(const RigidGeometry& geometry){
  std::map<std::string,int> curves,surfaces;for(const auto&[edge,count]:geometry.edges)curves[std::get<2>(edge)]+=count;for(const auto&[face,count]:geometry.faces)surfaces[face.surface]+=count;
  std::ostringstream out;out<<geometry.points.size()<<'|' ;int ec=0,fc=0;for(const auto&[_,v]:geometry.edges)ec+=v;for(const auto&[_,v]:geometry.faces)fc+=v;out<<ec<<'|'<<fc;for(const auto&[k,v]:curves)out<<"|c:"<<k<<':'<<v;for(const auto&[k,v]:surfaces)out<<"|s:"<<k<<':'<<v;return out.str();
}

}  // namespace

RigidGeometry load_rigid_geometry(const std::string& path) {
  const Entities entities=parse_step(path);const auto ids=reachable(solid_root(entities),entities);const auto points=vertex_points(ids,entities);
  std::map<Point,int> point_index;for(int i=0;i<static_cast<int>(points.size());++i)point_index[points[i]]=i;
  std::map<int,Point> coordinates;for(int id:ids){const auto&entity=entities.at(id);if(entity.kind!="VERTEX_POINT")continue;for(int ref:entity.refs)if(entity_kind(ref,entities)=="CARTESIAN_POINT")if(auto p=cartesian_point(entities.at(ref))){coordinates[id]={rounded10((*p)[0]),rounded10((*p)[1]),rounded10((*p)[2])};break;}}
  const auto typed_edge=[&](int edge)->std::optional<EdgeKey>{std::vector<int>endpoints;for(int ref:entities.at(edge).refs)if(entity_kind(ref,entities)=="VERTEX_POINT"){endpoints.push_back(ref);if(endpoints.size()==2)break;}if(endpoints.size()!=2||!coordinates.contains(endpoints[0])||!coordinates.contains(endpoints[1]))return std::nullopt;int a=point_index.at(coordinates.at(endpoints[0])),b=point_index.at(coordinates.at(endpoints[1]));if(a>b)std::swap(a,b);return EdgeKey{a,b,curve_for_edge(edge,entities)};};
  RigidGeometry result;result.points=points;for(int id:ids)if(entities.at(id).kind=="EDGE_CURVE")if(auto edge=typed_edge(id))result.edges[*edge]++;
  for(int id:ids)if(entities.at(id).kind=="ADVANCED_FACE"){std::vector<EdgeKey>boundary;for(int edge:face_edge_curves(id,entities))if(auto item=typed_edge(edge))boundary.push_back(*item);std::sort(boundary.begin(),boundary.end());result.faces[{surface_for_face(id,entities),boundary}]++;}
  return result;
}

std::optional<RigidTransform> find_rigid_transform(const std::vector<Point>& source,const std::vector<Point>& target,double tolerance,const EdgeSignature*source_edges,const EdgeSignature*target_edges,const FaceSignature*source_faces,const FaceSignature*target_faces){
  if (source.size() != target.size() || source.size() < 3) return std::nullopt;
  const auto sf=fingerprints(source,tolerance),tf=fingerprints(target,tolerance);
  int a=1,b=0;double longest=-1;for(int left=0;left<static_cast<int>(source.size());++left)for(int right=0;right<left;++right){double d=distance(source[left],source[right]);if(d>longest){longest=d;a=left;b=right;}}
  const Point line=sub(source[b],source[a]);const double line_length=norm(line);int c=-1;double altitude=-1;for(int i=0;i<static_cast<int>(source.size());++i)if(i!=a&&i!=b){double h=norm(cross(line,sub(source[i],source[a])))/line_length;if(h>altitude){altitude=h;c=i;}}if(c<0||altitude<=tolerance)return std::nullopt;
  std::vector<int>ta,tb,tc;for(int i=0;i<static_cast<int>(target.size());++i){if(fingerprint_compatible(tf[i],sf[a]))ta.push_back(i);if(fingerprint_compatible(tf[i],sf[b]))tb.push_back(i);if(fingerprint_compatible(tf[i],sf[c]))tc.push_back(i);}const double dab=distance(source[a],source[b]),dac=distance(source[a],source[c]),dbc=distance(source[b],source[c]);int attempts=0;
  for(int ia:ta)for(int ib:tb){if(ia==ib||std::abs(distance(target[ia],target[ib])-dab)>tolerance)continue;for(int ic:tc){if(ic==ia||ic==ib||std::abs(distance(target[ia],target[ic])-dac)>tolerance||std::abs(distance(target[ib],target[ic])-dbc)>tolerance)continue;if(++attempts>10000)return std::nullopt;const Matrix3 r=rotation(frame(source[a],source[b],source[c]),frame(target[ia],target[ib],target[ic]));const Point translation=sub(target[ia],matvec(r,source[a]));std::vector<Point>transformed;for(const auto&p:source)transformed.push_back(add(matvec(r,p),translation));auto errors=match_points(transformed,target,tolerance);if(!errors)continue;
    if(source_edges&&target_edges){EdgeSignature remapped;for(const auto&[edge,count]:*source_edges){int l=errors->mapping[std::get<0>(edge)],rr=errors->mapping[std::get<1>(edge)];if(l>rr)std::swap(l,rr);remapped[{l,rr,std::get<2>(edge)}]+=count;}if(remapped!=*target_edges)continue;}
    if(source_faces&&target_faces){FaceSignature remapped;for(const auto&[face,count]:*source_faces){std::vector<EdgeKey>boundary;for(const auto&edge:face.boundary){int l=errors->mapping[std::get<0>(edge)],rr=errors->mapping[std::get<1>(edge)];if(l>rr)std::swap(l,rr);boundary.emplace_back(l,rr,std::get<2>(edge));}std::sort(boundary.begin(),boundary.end());remapped[{face.surface,boundary}]+=count;}if(remapped!=*target_faces)continue;}
    auto[axis,angle]=axis_angle(r);return RigidTransform{r,translation,axis,angle,errors->rms,errors->maximum};}}
  return std::nullopt;
}

std::vector<int> refine_candidate_groups_rigid(const std::vector<int>& candidate,const std::vector<RigidGeometry>& geometries,double tolerance){
  if (candidate.size() != geometries.size())
    throw std::invalid_argument("candidate/geometries length mismatch");
  std::map<int,std::vector<int>> groups;for(int i=0;i<static_cast<int>(candidate.size());++i)groups[candidate[i]].push_back(i);std::vector<std::vector<int>>partitions;
  for(const auto&[_,members]:groups){std::vector<int>remaining=members;while(!remaining.empty()){int reference=remaining.front();std::vector<int>passed{reference},failed;for(std::size_t i=1;i<remaining.size();++i){int item=remaining[i];const auto&a=geometries[reference];const auto&b=geometries[item];if(find_rigid_transform(a.points,b.points,tolerance,&a.edges,&b.edges,&a.faces,&b.faces))passed.push_back(item);else failed.push_back(item);}partitions.push_back(passed);remaining=failed;}}
  std::sort(partitions.begin(),partitions.end(),[](const auto&a,const auto&b){return a.front()<b.front();});std::vector<int>result(candidate.size());for(int g=0;g<static_cast<int>(partitions.size());++g)for(int i:partitions[g])result[i]=g+1;return result;
}

std::vector<int> full_rigid_group(const std::vector<RigidGeometry>& geometries,double tolerance){
  std::map<std::string,std::vector<std::pair<int,int>>>roots;std::vector<int>assignments;int group_count=0;for(int i=0;i<static_cast<int>(geometries.size());++i){auto&compatible=roots[invariant_key(geometries[i])];int assigned=0;for(const auto&[reference,group]:compatible){const auto&a=geometries[reference];const auto&b=geometries[i];if(find_rigid_transform(a.points,b.points,tolerance,&a.edges,&b.edges,&a.faces,&b.faces)){assigned=group;break;}}if(!assigned){assigned=++group_count;compatible.emplace_back(i,assigned);}assignments.push_back(assigned);}return assignments;
}

}  // namespace mbd
