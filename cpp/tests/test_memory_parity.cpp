#include <mbd_occt_fast/features.hpp>
#include <mbd_occt_fast/classifier.hpp>
#include <mbd/step_graph.hpp>
#include <STEPControl_Reader.hxx>
#include <TopExp_Explorer.hxx>
#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include <cmath>
#include <chrono>

using json=nlohmann::json;
int main(int argc,char** argv) {
  try {
    if(argc!=3) throw std::runtime_error("usage: mbd_memory_parity source.step python_report.json");
    STEPControl_Reader reader;
    if(reader.ReadFile(argv[1])!=IFSelect_RetDone || reader.TransferRoots()<=0) return 1;
    json baseline; std::ifstream(argv[2])>>baseline;
    std::vector<mbd::occt_fast::Body> bodies;
    double histogram_error=0, exact_error=0;
    json mismatches=json::array();
    std::size_t i=0;
    for(TopExp_Explorer solids(reader.OneShape(),TopAbs_SOLID);solids.More();solids.Next(),++i) {
      auto f=mbd::occt_fast::describe(solids.Current());
      const auto& row=baseline.at("parts").at(i);
      const auto& expected=row.at("descriptor");
      auto reference=f;
      reference.exact.volume=row.at("exact").at("volume");
      reference.exact.area=row.at("exact").at("area");
      reference.exact.edge_length=row.at("exact").at("edge_length");
      reference.exact.moments=row.at("exact").at("moments").get<std::array<double,3>>();
      reference.graph.counts=expected.at("counts").get<std::map<std::string,int>>();
      reference.graph.surface_histogram=expected.at("surface_histogram").get<std::map<std::string,int>>();
      reference.graph.curve_histogram=expected.at("curve_histogram").get<std::map<std::string,int>>();
      reference.graph.wl_histogram=expected.at("wl_histogram").get<std::map<std::string,int>>();
      reference.graph.wl_family_histogram=expected.at("wl_family_histogram").get<std::map<std::string,int>>();
      reference.graph.distance_histogram=expected.at("distance_histogram").get<std::vector<double>>();
      const auto& g=f.graph;
      json actual={{"counts",g.counts},{"surface_histogram",g.surface_histogram},
        {"curve_histogram",g.curve_histogram},{"wl_histogram",g.wl_histogram},
        {"wl_family_histogram",g.wl_family_histogram},{"graph",g.graph}};
      for(auto it=actual.begin();it!=actual.end();++it)
        if(it.value()!=expected.at(it.key()))
          mismatches.push_back({{"part",i+1},{"field",it.key()},{"actual",it.value()},{"expected",expected.at(it.key())}});
      for(std::size_t j=0;j<g.distance_histogram.size();++j)
        histogram_error=std::max(histogram_error,std::abs(g.distance_histogram[j]-expected.at("distance_histogram").at(j).get<double>()));
      for(const auto& v:std::vector<std::pair<const char*,double>>{{"volume",f.exact.volume},{"area",f.exact.area},{"edge_length",f.exact.edge_length}}) {
        double expected_value=row.at("exact").at(v.first);
        exact_error=std::max(exact_error,std::abs(v.second-expected_value)/std::max(1e-12,std::abs(expected_value)));
      }
      for(std::size_t j=0;j<3;++j) {
        double expected_value=reference.exact.moments[j];
        exact_error=std::max(exact_error,std::abs(f.exact.moments[j]-expected_value)/std::max(1e-12,std::abs(expected_value)));
      }
      bodies.push_back({std::to_string(i+1),solids.Current()});
    }
    const auto start=std::chrono::steady_clock::now();
    const auto r=mbd::occt_fast::classify(bodies);
    const auto seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    double distance_error=0;
    for(std::size_t a=0;a<r.body_ids.size();++a) for(std::size_t b=0;b<a;++b) {
      const double expected_distance=baseline.at("parity_distance_matrix")
        .at(std::stoi(r.body_ids[a])-1).at(std::stoi(r.body_ids[b])-1);
      distance_error=std::max(distance_error,std::abs(r.distances[a][b]-expected_distance));
    }
    std::vector<int> expected(bodies.size());
    for(const auto& group:baseline.at("candidate_groups"))
      for(int part:group.at("parts")) expected.at(part-1)=group.at("group");
    bool equal=r.skipped.empty()&&i==baseline.at("parts").size();
    for(std::size_t a=0;a<r.body_ids.size();++a)for(std::size_t b=0;b<a;++b)
      equal=equal&&((r.assignments[a]==r.assignments[b])==
        (expected.at(std::stoi(r.body_ids[a])-1)==expected.at(std::stoi(r.body_ids[b])-1)));
    json summary={{"parts",i},{"groups",r.groups.size()},{"partition_equal",equal},
      {"descriptor_mismatches",mismatches},{"histogram_max_error",histogram_error},{"exact_max_relative_error",exact_error},
      {"distance_matrix_max_error",distance_error},{"memory_classification_seconds",seconds}};
    std::cout<<summary.dump(2)<<'\n';
    // Native geometry vs STEP text includes quantized coordinates. Same-feature
    // distance arithmetic is separately checked at 1e-12 by python_cpp_parity.
    return equal&&mismatches.empty()&&histogram_error<=1e-10&&exact_error<=1e-10&&distance_error<=1e-10?0:2;
  } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
