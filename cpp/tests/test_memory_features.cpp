#include <mbd_occt_fast/features.hpp>
#include <mbd/step_graph.hpp>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <STEPControl_Writer.hxx>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <cmath>
#include <iostream>
#include <fstream>

using json=nlohmann::json;
json maps(const mbd::fast::GraphDescriptor& g) {
  return {{"counts",g.counts},{"surfaces",g.surface_histogram},{"curves",g.curve_histogram},
    {"wl",g.wl_histogram},{"family",g.wl_family_histogram},{"graph",g.graph}};
}
int main(int argc,char** argv) {
  if(argc!=2) return 1;
  const std::filesystem::path dir(argv[1]);
  std::filesystem::create_directories(dir);
  std::vector<std::pair<std::string,TopoDS_Shape>> shapes{
    {"box",BRepPrimAPI_MakeBox(2,3,4).Shape()},
    {"cylinder",BRepPrimAPI_MakeCylinder(2,4).Shape()},
    {"cone",BRepPrimAPI_MakeCone(3,1,4).Shape()},
    {"pointed_cone",BRepPrimAPI_MakeCone(3,0,4).Shape()},
    {"sphere",BRepPrimAPI_MakeSphere(2).Shape()},
    {"torus",BRepPrimAPI_MakeTorus(4,1).Shape()},
    {"nurbs_box",BRepBuilderAPI_NurbsConvert(BRepPrimAPI_MakeBox(2,3,4).Shape(),true).Shape()},
    {"nurbs_cylinder",BRepBuilderAPI_NurbsConvert(BRepPrimAPI_MakeCylinder(2,4).Shape(),true).Shape()},
    {"hole",BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(10,10,4).Shape(),
      BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5,5,-1),gp_Dir(0,0,1)),2,6).Shape()).Shape()}};
  bool ok=true;
  json native_rows=json::array();
  for(const auto& [name,shape]:shapes) {
    auto native=mbd::occt_fast::describe(shape);
    auto path=dir/(name+".step");
    STEPControl_Writer writer;
    if(writer.Transfer(shape,STEPControl_AsIs)!=IFSelect_RetDone ||
       writer.Write(path.string().c_str())!=IFSelect_RetDone) return 1;
    auto ref=mbd::describe_normalized_step(path.string(),3,std::cbrt(native.exact.volume)).second;
    native_rows.push_back({{"name",name},{"exact",{{"volume",native.exact.volume},
      {"area",native.exact.area},{"edge_length",native.exact.edge_length},{"moments",native.exact.moments}}},
      {"descriptor",maps(native.graph)},{"histogram",native.graph.distance_histogram}});
    auto a=maps(native.graph),b=maps(ref);
    for(auto it=a.begin();it!=a.end();++it) if(it.value()!=b.at(it.key())) {
      std::cerr<<name<<" "<<it.key()<<"\n native "<<it.value()<<"\n STEP "<<b.at(it.key())<<'\n';
      ok=false;
    }
    double error=0;
    for(std::size_t i=0;i<ref.distance_histogram.size();++i)
      error=std::max(error,std::abs(native.graph.distance_histogram[i]-ref.distance_histogram[i]));
    if(error>1e-10) {ok=false;std::cerr<<name<<" histogram "<<error<<'\n';}
  }
  std::ofstream(dir/"native.json")<<native_rows.dump(2);
  return ok?0:2;
}
