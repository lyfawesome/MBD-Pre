#include <mbd_occt_fast/classifier.hpp>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <TopExp_Explorer.hxx>
#include <gp_Ax1.hxx>
#include <stdexcept>
#include <iostream>
#include <algorithm>
#include <limits>
#include <filesystem>

std::vector<std::filesystem::path> files() {
  std::vector<std::filesystem::path> result;
  for (const auto& entry:std::filesystem::recursive_directory_iterator("."))
    result.push_back(entry.path());
  std::sort(result.begin(),result.end());
  return result;
}

void require(bool value,const char* message) {
  if (!value) throw std::runtime_error(message);
}

int main() {
  try {
    const auto before=files();
    using namespace mbd::occt_fast;
    const auto box=BRepPrimAPI_MakeBox(2,3,4).Shape();
    gp_Trsf tr; tr.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(1,2,3)),0.61);
    tr.SetTranslationPart(gp_Vec(11,-2,7));
    const auto moved=BRepBuilderAPI_Transform(box,tr,true).Shape();
    const auto larger=BRepPrimAPI_MakeBox(4,6,8).Shape();
    const auto cylinder=BRepPrimAPI_MakeCylinder(1,4).Shape();
    const std::vector<Body> bodies{{"a",box},{"b",moved},{"c",larger},{"d",cylinder},{"bad",{}}};
    auto r=classify(bodies);
    require(r.groups.size()==3 && r.groups[0]==std::vector<std::string>{"a","b"},"strict grouping");
    require(r.skipped.size()==1 && r.skipped[0].body_id=="bad","null diagnostics");
    auto reverse=bodies; std::reverse(reverse.begin(),reverse.end());
    require(classify(reverse).groups==r.groups,"stable IDs under reordering");
    Options family; family.mode=Mode::family;
    require(classify(bodies,family).groups[0]==std::vector<std::string>{"a","b","c"},"family grouping");
    BRep_Builder builder; TopoDS_Compound compound; builder.MakeCompound(compound);
    builder.Add(compound,box); builder.Add(compound,moved);
    const auto compound_moved=BRepBuilderAPI_Transform(compound,tr,true).Shape();
    auto c=classify({{"whole",compound},{"copy",compound_moved},{"single",box}});
    require(c.groups.size()==2 && c.groups[0]==std::vector<std::string>{"copy","whole"},"whole multi-solid body");
    TopoDS_Compound mixed; builder.MakeCompound(mixed);
    builder.Add(mixed, box);
    builder.Add(mixed, TopExp_Explorer(box, TopAbs_FACE).Current());
    const auto rejected=classify({{"mixed",mixed},{"valid",box}});
    require(rejected.body_ids==std::vector<std::string>{"valid"} &&
            rejected.skipped.size()==1,"mixed solid and loose face must be diagnosed");
    require(classify({}).groups.empty(),"empty input");
    bool threw=false; try { classify({{"x",box},{"x",box}}); } catch(const std::invalid_argument&) { threw=true; }
    require(threw,"duplicate IDs must fail");
    threw=false; try { classify({{"",box}}); } catch(const std::invalid_argument&) { threw=true; }
    require(threw,"empty IDs must fail");
    Options invalid; invalid.threshold=std::numeric_limits<double>::quiet_NaN();
    threw=false; try { classify(bodies,invalid); } catch(const std::invalid_argument&) { threw=true; }
    require(threw,"nonfinite options must fail");
    invalid={}; invalid.wl_iterations=-1;
    threw=false; try { classify(bodies,invalid); } catch(const std::invalid_argument&) { threw=true; }
    require(threw,"negative WL depth must fail");
    const auto all_bad=classify({{"bad",{}}});
    require(all_bad.groups.empty()&&all_bad.skipped.size()==1,"all skipped is an empty successful result");
    require(files()==before,"classification must not create filesystem artifacts");
    std::cout<<"pure-memory classifier tests passed\n";
  } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
