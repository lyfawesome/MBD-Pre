#include "mbd/fast.hpp"
#include "mbd/rigid.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

mbd::PartFeatures part(int index, double scale = 1.0) {
  mbd::PartFeatures value;
  value.index = index;
  value.exact = {index, 8 * std::pow(scale, 3), 24 * std::pow(scale, 2),
                 24 * scale, {10 * std::pow(scale, 5), 8 * std::pow(scale, 5), 6 * std::pow(scale, 5)}};
  value.graph.counts = {{"ADVANCED_FACE", 6}, {"EDGE_CURVE", 12}};
  value.graph.surface_histogram = {{"PLANE", 6}};
  value.graph.curve_histogram = {{"LINE", 24}};
  value.graph.wl_histogram = {{"0:a", 6}, {"1:b", 6}};
  value.graph.wl_family_histogram = value.graph.wl_histogram;
  value.graph.distance_histogram = {0.25, 0.5, 0.25};
  return value;
}

void test_fast_compare() {
  auto first = part(1), second = part(2);
  const auto distance = mbd::compare(first, second, "strict");
  require(std::abs(distance.total) < 1e-14, "identical feature distance must be zero");
  auto large = part(3, 2.0);
  require(mbd::compare(first, large, "strict").total == 1.0, "strict size gate must reject scale change");
  require(std::abs(mbd::compare(first, large, "family").total) < 1e-14, "family mode must ignore uniform scale");
}

void test_complete_link() {
  const std::vector<std::vector<double>> matrix{{0, .1, .2}, {.1, 0, .1}, {.2, .1, 0}};
  const auto groups = mbd::density_complete_link(matrix, .11);
  require(groups[0] == groups[1] && groups[0] != groups[2], "complete-link must break a similarity chain");
  mbd::verify_assignments(matrix, groups, .11);

  const std::vector<std::vector<double>> tied{{0, .1, .1}, {.1, 0, .2}, {.1, .2, 0}};
  const auto first = mbd::density_complete_link(tied, .11, {"a", "b", "c"});
  const std::vector<int> order{2,1,0};
  std::vector permuted(3, std::vector<double>(3));
  for(int i=0;i<3;++i)for(int j=0;j<3;++j)permuted[i][j]=tied[order[i]][order[j]];
  const auto raw = mbd::density_complete_link(permuted, .11, {"c", "b", "a"});
  std::vector<int> second(3);for(int i=0;i<3;++i)second[order[i]]=raw[i];
  for(int a=0;a<3;++a)for(int b=0;b<a;++b)
    require((first[a]==first[b])==(second[a]==second[b]), "stable keys must preserve partition under permutation");
}

void test_rigid() {
  const std::vector<mbd::Point> source{{0,0,0},{2,0,0},{0,1,0},{0,0,3},{1.2,.4,2.1}};
  const double angle=.61,c=std::cos(angle),s=std::sin(angle);
  std::vector<mbd::Point> target;
  for(const auto&p:source)target.push_back({p[0]*c-p[1]*s+7,p[0]*s+p[1]*c-4,p[2]+2.5});
  const auto transform=mbd::find_rigid_transform(source,target,1e-8);
  require(transform.has_value(), "proper rotation and translation must match");
  require(transform->max_vertex_error<1e-10, "rigid residual must match Python tolerance");
  std::vector<mbd::Point> mirror;for(const auto&p:source)mirror.push_back({-p[0]+5,p[1]-3,p[2]+1});
  require(!mbd::find_rigid_transform(source,mirror,1e-8), "chiral mirror must not be accepted");
  const mbd::EdgeSignature source_edges{{{0, 1, "LINE"}, 1}, {{0, 2, "LINE"}, 1}};
  const mbd::EdgeSignature different_edges{{{0, 1, "LINE"}, 1}, {{1, 2, "LINE"}, 1}};
  require(!mbd::find_rigid_transform(source,target,1e-8,&source_edges,&different_edges),
          "typed edge topology mismatch must be rejected");
}

void test_near_180_axis_angle() {
  const std::vector<mbd::Point> source{{0,0,0},{2,0,0},{.2,1.3,0},{.1,.4,2.7},{1.4,.3,1.1}};
  mbd::Point axis{.5355737329905428,.8444884703360814,-2e-12};
  double axis_norm=std::sqrt(axis[0]*axis[0]+axis[1]*axis[1]+axis[2]*axis[2]);
  for(double& value:axis)value/=axis_norm;
  const double angle=std::acos(-1.0)-2e-11,c=std::cos(angle),s=std::sin(angle),one=1-c;
  const auto rotate=[&](const mbd::Point&p){const double d=axis[0]*p[0]+axis[1]*p[1]+axis[2]*p[2];return mbd::Point{
    p[0]*c+(axis[1]*p[2]-axis[2]*p[1])*s+axis[0]*d*one+3,
    p[1]*c+(axis[2]*p[0]-axis[0]*p[2])*s+axis[1]*d*one-2,
    p[2]*c+(axis[0]*p[1]-axis[1]*p[0])*s+axis[2]*d*one+1};};
  std::vector<mbd::Point> target;for(const auto&p:source)target.push_back(rotate(p));
  const auto transform=mbd::find_rigid_transform(source,target,1e-8);
  require(transform.has_value(),"near-180-degree rotation must match");
  require(std::abs(transform->angle_degrees-180.0)<1e-7,"near-180-degree axis-angle must be stable");
}

void test_adjacent_fingerprint_bins() {
  const std::vector<mbd::Point> source{
    {.37286677651407407,.6244865760167085,.22795976272212315},{.2026252770582384,.3859661844073685,.1864784582738538},{.1125726393278852,.14255163554197614,.2283446307104201},{.9408962666789277,.5210990853341416,.03283467141067353},{.15335044968564993,.3925332051210709,.3830499535657014},{.39061823252398575,.961947452384876,.1684877845891668},{.45370827333883534,.7969009090293485,.3929753406948706},{.920628573983454,.6769454116932154,.26607099468967854}};
  const std::vector<mbd::Point> target{
    {3.860685706834955,-2.28613401492528,2.227959762394246},{3.8931793583360643,-2.5773698443703426,2.186478458996319},{3.9886416008186374,-2.8187141634836768,2.228344630077618},{4.352610714917745,-1.9838820327419835,2.0328346717111767},{3.8521096588238186,-2.6053772370999,2.383049952610936},{3.6486080266277336,-2.0230408475085344,2.1684877851207487},{3.805766475640744,-2.1037993558174226,2.3929753402215805},{4.233476008148363,-1.8813843307844362,2.266070994860232}};
  const auto transform=mbd::find_rigid_transform(source,target,1e-5);
  require(transform.has_value()&&transform->max_vertex_error<2e-9,"adjacent fingerprint bins must remain compatible");
}

void test_global_rigid_grouping() {
  mbd::RigidGeometry first;
  first.points={{0,0,0},{2,0,0},{.2,1.3,0},{.1,.4,2.7},{1.4,.3,1.1}};
  mbd::RigidGeometry second=first,mirror=first;
  const double angle=.37,c=std::cos(angle),s=std::sin(angle);
  for(auto& p:second.points)p={p[0]*c-p[1]*s+4,p[0]*s+p[1]*c-2,p[2]+1};
  for(auto& p:mirror.points)p={-p[0]+5,p[1]-3,p[2]+1};
  const auto groups=mbd::full_rigid_group({first,second,mirror},1e-8);
  require(groups[0]==groups[1]&&groups[0]!=groups[2],"global rigid grouping must merge rotations and split mirrors");
}

}  // namespace

int main() {
  try {
    test_fast_compare();
    test_complete_link();
    test_rigid();
    test_near_180_axis_angle();
    test_adjacent_fingerprint_bins();
    test_global_rigid_grouping();
    std::cout << "all C++ algorithm tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "test failure: " << error.what() << '\n';
    return 1;
  }
}
