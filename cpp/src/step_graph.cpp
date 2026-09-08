#include "mbd/step_graph.hpp"
#include <mbd_fast/topology.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace mbd {
namespace {

struct Entity { std::string kind, body; std::vector<int> refs; };
using Entities = std::map<int, Entity>;
using Adjacency = std::map<int, std::vector<std::pair<int, std::string>>>;
using Point = std::array<double, 3>;

const std::set<std::string> surfaces{
  "PLANE","CYLINDRICAL_SURFACE","CONICAL_SURFACE","SPHERICAL_SURFACE",
  "TOROIDAL_SURFACE","B_SPLINE_SURFACE_WITH_KNOTS","BEZIER_SURFACE",
  "SURFACE_OF_REVOLUTION","SURFACE_OF_LINEAR_EXTRUSION","OFFSET_SURFACE"};
const std::set<std::string> curves{
  "LINE","CIRCLE","ELLIPSE","B_SPLINE_CURVE_WITH_KNOTS","B_SPLINE_CURVE",
  "RATIONAL_B_SPLINE_CURVE","BEZIER_CURVE","SURFACE_CURVE","PCURVE","TRIMMED_CURVE"};
const std::set<std::string> base_curves{
  "LINE","CIRCLE","ELLIPSE","B_SPLINE_CURVE_WITH_KNOTS","B_SPLINE_CURVE",
  "RATIONAL_B_SPLINE_CURVE","BEZIER_CURVE"};
const std::set<std::string> solids{"MANIFOLD_SOLID_BREP","BREP_WITH_VOIDS","FACETED_BREP"};

std::string read_file(const std::string& path){std::ifstream in(path,std::ios::binary);if(!in)throw std::runtime_error("cannot open STEP file: "+path);std::ostringstream out;out<<in.rdbuf();return out.str();}
std::vector<int> refs(const std::string& body){static const std::regex re(R"(#(\d+))");std::vector<int>v;for(std::sregex_iterator i(body.begin(),body.end(),re),e;i!=e;++i)v.push_back(std::stoi((*i)[1]));return v;}
Entities parse(const std::string& path){
  const std::string text=read_file(path);static const std::regex simple(R"(^\s*([A-Z][A-Z0-9_]*)\s*\(([\s\S]*)\)\s*$)");static const std::regex kinds_re(R"(([A-Z][A-Z0-9_]*)\s*\()");const std::vector<std::string>priority{"B_SPLINE_CURVE_WITH_KNOTS","RATIONAL_B_SPLINE_CURVE","B_SPLINE_CURVE","B_SPLINE_SURFACE_WITH_KNOTS","RATIONAL_B_SPLINE_SURFACE","B_SPLINE_SURFACE"};Entities result;std::size_t pos=0;
  while((pos=text.find('#',pos))!=std::string::npos){std::size_t cur=pos+1;while(cur<text.size()&&std::isdigit(static_cast<unsigned char>(text[cur])))++cur;if(cur==pos+1){++pos;continue;}int id=std::stoi(text.substr(pos+1,cur-pos-1));while(cur<text.size()&&std::isspace(static_cast<unsigned char>(text[cur])))++cur;if(cur>=text.size()||text[cur]!='='){pos=cur;continue;}std::size_t begin=++cur;bool quote=false;while(cur<text.size()){if(text[cur]=='\''){if(quote&&cur+1<text.size()&&text[cur+1]=='\''){cur+=2;continue;}quote=!quote;}if(!quote&&text[cur]==';')break;++cur;}if(cur>=text.size())break;std::string value=text.substr(begin,cur-begin);auto first=value.find_first_not_of(" \t\r\n"),last=value.find_last_not_of(" \t\r\n");if(first==std::string::npos){pos=cur+1;continue;}value=value.substr(first,last-first+1);std::smatch m;std::string kind,body;if(std::regex_match(value,m,simple)){kind=m[1];body=m[2];}else{std::vector<std::string>ks;for(std::sregex_iterator i(value.begin(),value.end(),kinds_re),e;i!=e;++i)ks.push_back((*i)[1]);if(ks.empty()){pos=cur+1;continue;}kind=ks.front();for(const auto&p:priority)if(std::find(ks.begin(),ks.end(),p)!=ks.end()){kind=p;break;}body=value;}result[id]={kind,body,refs(body)};pos=cur+1;}
  if(result.empty()) throw std::runtime_error("no STEP entities found");
  return result;
}
std::string kind(int id,const Entities&e){auto i=e.find(id);return i==e.end()?"":i->second.kind;}
int root(const Entities&e){for(const auto&[id,item]:e)if(solids.contains(item.kind))return id;throw std::runtime_error("no supported solid");}
std::set<int> reachable(int start,const Entities&e){std::set<int>seen;std::vector<int>stack{start};while(!stack.empty()){int id=stack.back();stack.pop_back();if(seen.contains(id)||!e.contains(id))continue;seen.insert(id);stack.insert(stack.end(),e.at(id).refs.begin(),e.at(id).refs.end());}return seen;}
std::string label(const Entities&e,int id){static const std::regex string_re("'((?:''|[^'])*)'");std::smatch m;if(std::regex_search(e.at(id).body,m,string_re)){std::string value=m[1];for(std::size_t p=0;(p=value.find("''",p))!=std::string::npos;)value.replace(p,2,"'");auto first=value.find_first_not_of(" \t\r\n"),last=value.find_last_not_of(" \t\r\n");if(first!=std::string::npos){value=value.substr(first,last-first+1);std::string upper=value;std::transform(upper.begin(),upper.end(),upper.begin(),::toupper);if(!value.empty()&&upper!="NONE"&&upper!="SOLID")return value;}}return "solid_"+std::to_string(id);}

std::optional<int> oriented_edge(int id,const Entities&e){if(!e.contains(id))return{};if(e.at(id).kind=="EDGE_CURVE")return id;if(e.at(id).kind=="ORIENTED_EDGE")for(auto i=e.at(id).refs.rbegin();i!=e.at(id).refs.rend();++i)if(kind(*i,e)=="EDGE_CURVE")return*i;return{};}
std::vector<int> face_edges(int face,const Entities&e){std::vector<int>result;for(int bound:e.at(face).refs){auto k=kind(bound,e);if(k!="FACE_BOUND"&&k!="FACE_OUTER_BOUND")continue;for(int loop:e.at(bound).refs)if(kind(loop,e)=="EDGE_LOOP")for(int item:e.at(loop).refs)if(auto edge=oriented_edge(item,e))result.push_back(*edge);}return result;}
const Entity* face_surface(int face,const Entities&e){for(auto i=e.at(face).refs.rbegin();i!=e.at(face).refs.rend();++i)if(e.contains(*i)){const auto&item=e.at(*i);if(surfaces.contains(item.kind)||item.kind.find("SURFACE")!=std::string::npos)return&item;}return nullptr;}
const Entity* edge_curve(int edge,const Entities&e){std::deque<int>queue(e.at(edge).refs.begin(),e.at(edge).refs.end());std::set<int>seen;const Entity*fallback=nullptr;while(!queue.empty()){int id=queue.front();queue.pop_front();if(seen.contains(id))continue;seen.insert(id);if(!e.contains(id))continue;const auto&item=e.at(id);if(base_curves.contains(item.kind))return&item;if(curves.contains(item.kind)||item.kind.find("CURVE")!=std::string::npos){if(!fallback)fallback=&item;queue.insert(queue.begin(),item.refs.begin(),item.refs.end());}}return fallback;}

std::vector<double> numbers(std::string body){static const std::regex ref_re(R"(#\d+)");static const std::regex str_re("'((?:''|[^'])*)'");static const std::regex number_re(R"([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:E[-+]?\d+)?)",std::regex::icase);body=std::regex_replace(body,ref_re," ");body=std::regex_replace(body,str_re," ");std::vector<double>v;for(std::sregex_iterator i(body.begin(),body.end(),number_re),e;i!=e;++i)v.push_back(std::stod(i->str()));return v;}
std::pair<std::vector<double>,std::vector<double>> intrinsic(const Entity&item){auto v=numbers(item.body);int lengths=0,angles=0;if(item.kind=="CYLINDRICAL_SURFACE"||item.kind=="SPHERICAL_SURFACE"||item.kind=="OFFSET_SURFACE"||item.kind=="CIRCLE")lengths=1;else if(item.kind=="TOROIDAL_SURFACE"||item.kind=="ELLIPSE")lengths=2;else if(item.kind=="CONICAL_SURFACE"){lengths=1;angles=1;}if(!lengths&&!angles)return{};std::vector<double>l,a;if(lengths)l.assign(v.end()-angles-lengths,v.end()-angles);if(angles)a.assign(v.end()-angles,v.end());return{l,a};}
std::optional<Point> point(const Entity&item){if(item.kind!="CARTESIAN_POINT")return{};auto v=numbers(item.body);if(v.size()<3)return{};return Point{v[v.size()-3],v[v.size()-2],v[v.size()-1]};}
std::vector<Point> points(const std::set<int>&ids,const Entities&e){std::set<Point>result;for(int id:ids)if(e.at(id).kind=="VERTEX_POINT")for(int ref:e.at(id).refs)if(kind(ref,e)=="CARTESIAN_POINT")if(auto p=point(e.at(ref)))result.insert({std::round((*p)[0]*1e10)/1e10,std::round((*p)[1]*1e10)/1e10,std::round((*p)[2]*1e10)/1e10});return{result.begin(),result.end()};}

}  // namespace

std::pair<std::string,GraphDescriptor> describe_normalized_step(
    const std::string& path, int iterations, double part_scale) {
  const auto entities=parse(path);
  const int solid=root(entities);
  const auto ids=reachable(solid,entities);
  fast::PartTopology topology;
  std::map<int,int> edge_ids;
  const auto geometry=[](const Entity* item,const char* unknown) {
    if (!item) return fast::GeometryLabel{unknown,{}, {}};
    auto [lengths,angles]=intrinsic(*item);
    return fast::GeometryLabel{item->kind,std::move(lengths),std::move(angles)};
  };
  for (int id:ids) {
    ++topology.counts[entities.at(id).kind];
    if (entities.at(id).kind=="EDGE_CURVE") {
      edge_ids[id]=static_cast<int>(topology.edges.size());
      topology.edges.push_back(geometry(edge_curve(id,entities),"UNKNOWN_CURVE"));
    }
  }
  for (int id:ids) {
    if (entities.at(id).kind!="ADVANCED_FACE") continue;
    fast::FaceTopology face;
    face.surface=geometry(face_surface(id,entities),"UNKNOWN_SURFACE");
    for (int ref:entities.at(id).refs) {
      const auto k=kind(ref,entities);
      if (k=="FACE_BOUND" || k=="FACE_OUTER_BOUND") ++face.bounds;
    }
    for (int edge:face_edges(id,entities)) face.edge_uses.push_back(edge_ids.at(edge));
    topology.faces.push_back(std::move(face));
  }
  topology.vertices=points(ids,entities);
  return {label(entities,solid),fast::describe_topology(topology,iterations,part_scale)};
}

} // namespace mbd
