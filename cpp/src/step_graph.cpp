#include "mbd/step_graph.hpp"

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
std::string gformat(double value){std::ostringstream out;out<<std::setprecision(6)<<std::defaultfloat<<value;return out.str();}
std::string parameter(const Entity&item,double part_scale,bool family){auto[l,a]=intrinsic(item);double scale=family?std::max(std::abs(part_scale),1e-15):1.0;std::vector<std::string>tokens;for(double value:l){double magnitude=std::abs(value)/scale;if(magnitude<1e-15){tokens.push_back("L0");continue;}double rounded=std::nearbyint(std::log10(magnitude)*16)/16;if(rounded==0)rounded=0;tokens.push_back("L"+gformat(rounded));}for(double value:a){double rounded=std::nearbyint(value*360/std::acos(-1.0))/2;if(rounded==0)rounded=0;tokens.push_back("A"+gformat(rounded));}std::ostringstream out;for(std::size_t i=0;i<tokens.size();++i){if(i)out<<':';out<<tokens[i];}return out.str();}

constexpr std::array<std::uint64_t,8> IV{0x6a09e667f3bcc908ULL,0xbb67ae8584caa73bULL,0x3c6ef372fe94f82bULL,0xa54ff53a5f1d36f1ULL,0x510e527fade682d1ULL,0x9b05688c2b3e6c1fULL,0x1f83d9abfb41bd6bULL,0x5be0cd19137e2179ULL};
constexpr std::array<std::array<unsigned char,16>,12>SIGMA{{
{{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15}},{{14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3}},{{11,8,12,0,5,2,15,13,10,14,3,6,7,1,9,4}},{{7,9,3,1,13,12,11,14,2,6,5,10,4,0,15,8}},{{9,0,5,7,2,4,10,15,14,1,11,12,6,8,3,13}},{{2,12,6,10,0,11,8,3,4,13,7,5,15,14,1,9}},{{12,5,1,15,14,13,4,10,0,7,6,3,9,2,8,11}},{{13,11,7,14,12,1,3,9,5,0,15,4,8,6,2,10}},{{6,15,14,9,11,3,0,8,12,2,13,7,1,4,10,5}},{{10,2,8,4,7,6,1,5,15,11,9,14,3,12,13,0}},{{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15}},{{14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3}}}};
std::uint64_t rotr(std::uint64_t x,int n){return(x>>n)|(x<<(64-n));}
void mix(std::array<std::uint64_t,16>&v,int a,int b,int c,int d,std::uint64_t x,std::uint64_t y){v[a]=v[a]+v[b]+x;v[d]=rotr(v[d]^v[a],32);v[c]+=v[d];v[b]=rotr(v[b]^v[c],24);v[a]=v[a]+v[b]+y;v[d]=rotr(v[d]^v[a],16);v[c]+=v[d];v[b]=rotr(v[b]^v[c],63);}
void compress(std::array<std::uint64_t,8>&h,const unsigned char*block,std::uint64_t count,bool last){std::array<std::uint64_t,16>m{},v{};for(int i=0;i<16;++i)for(int j=0;j<8;++j)m[i]|=static_cast<std::uint64_t>(block[i*8+j])<<(8*j);for(int i=0;i<8;++i){v[i]=h[i];v[i+8]=IV[i];}v[12]^=count;if(last)v[14]=~v[14];for(int r=0;r<12;++r){const auto&s=SIGMA[r];mix(v,0,4,8,12,m[s[0]],m[s[1]]);mix(v,1,5,9,13,m[s[2]],m[s[3]]);mix(v,2,6,10,14,m[s[4]],m[s[5]]);mix(v,3,7,11,15,m[s[6]],m[s[7]]);mix(v,0,5,10,15,m[s[8]],m[s[9]]);mix(v,1,6,11,12,m[s[10]],m[s[11]]);mix(v,2,7,8,13,m[s[12]],m[s[13]]);mix(v,3,4,9,14,m[s[14]],m[s[15]]);}for(int i=0;i<8;++i)h[i]^=v[i]^v[i+8];}
std::string token(const std::string&input){constexpr int outlen=10;std::array<std::uint64_t,8>h=IV;h[0]^=0x01010000^outlen;std::uint64_t count=0;std::size_t offset=0;while(input.size()-offset>128){compress(h,reinterpret_cast<const unsigned char*>(input.data()+offset),count+=128,false);offset+=128;}std::array<unsigned char,128>last{};std::copy(input.begin()+static_cast<std::ptrdiff_t>(offset),input.end(),last.begin());count+=input.size()-offset;compress(h,last.data(),count,true);std::array<unsigned char,outlen>digest{};for(int i=0;i<outlen;++i)digest[i]=static_cast<unsigned char>(h[i/8]>>(8*(i%8)));std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto byte:digest)out<<std::setw(2)<<static_cast<int>(byte);return out.str();}

std::map<std::string,int> wl(const std::map<int,std::string>&node_labels,const Adjacency&adj,int iterations){std::map<int,std::string>labels;std::map<std::string,int>hist;for(const auto&[node,value]:node_labels){labels[node]=token("0|"+value);hist["0:"+labels[node]]++;}for(int level=1;level<=iterations;++level){std::map<int,std::string>next;for(const auto&[node,current]:labels){std::vector<std::string>neighbors;for(const auto&[other,edge]:adj.at(node))neighbors.push_back(edge+":"+labels.at(other));std::sort(neighbors.begin(),neighbors.end());std::ostringstream value;value<<current<<'|';for(std::size_t i=0;i<neighbors.size();++i){if(i)value<<'|';value<<neighbors[i];}next[node]=token(value.str());}labels=next;for(const auto&[_,value]:labels)hist[std::to_string(level)+":"+value]++;}return hist;}
std::optional<Point> point(const Entity&item){if(item.kind!="CARTESIAN_POINT")return{};auto v=numbers(item.body);if(v.size()<3)return{};return Point{v[v.size()-3],v[v.size()-2],v[v.size()-1]};}
std::vector<Point> points(const std::set<int>&ids,const Entities&e){std::set<Point>result;for(int id:ids)if(e.at(id).kind=="VERTEX_POINT")for(int ref:e.at(id).refs)if(kind(ref,e)=="CARTESIAN_POINT")if(auto p=point(e.at(ref)))result.insert({std::round((*p)[0]*1e10)/1e10,std::round((*p)[1]*1e10)/1e10,std::round((*p)[2]*1e10)/1e10});return{result.begin(),result.end()};}
double dist(const Point&a,const Point&b){return std::hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);}
std::vector<double> distance_hist(const std::vector<Point>&p,int bins=32){std::vector<double>h(bins);if(p.size()<2)return h;double diameter=0;for(std::size_t l=0;l<p.size();++l)for(std::size_t r=0;r<l;++r)diameter=std::max(diameter,dist(p[l],p[r]));if(diameter<1e-12)return h;for(std::size_t l=0;l<p.size();++l)for(std::size_t r=0;r<l;++r){double position=std::clamp(dist(p[l],p[r])/diameter*(bins-1),0.0,bins-1.0);int lower=static_cast<int>(std::floor(position)),upper=std::min(bins-1,lower+1);double fraction=position-lower;h[lower]+=1-fraction;h[upper]+=fraction;}double total=0;for(double v:h)total+=v;if(total==0)total=1;for(double&v:h)v/=total;return h;}
int components(const Adjacency&adj){std::set<int>remaining;for(const auto&[id,_]:adj)remaining.insert(id);int count=0;while(!remaining.empty()){++count;std::vector<int>stack{*remaining.begin()};remaining.erase(stack.back());while(!stack.empty()){int current=stack.back();stack.pop_back();for(const auto&[other,_]:adj.at(current))if(remaining.erase(other))stack.push_back(other);}}return count;}

}  // namespace

std::pair<std::string,GraphDescriptor> describe_normalized_step(const std::string&path,int iterations,double part_scale){
  const auto e=parse(path);const int solid=root(e);const auto ids=reachable(solid,e);std::map<std::string,int>all_counts;for(int id:ids)all_counts[e.at(id).kind]++;std::vector<int>faces;for(int id:ids)if(e.at(id).kind=="ADVANCED_FACE")faces.push_back(id);std::sort(faces.begin(),faces.end());std::map<int,std::vector<int>>edge_faces;std::map<int,std::string>labels,family_labels;std::map<std::string,int>surface_hist,curve_hist;int unknown_curves=0;
  for(int face:faces){auto edges=face_edges(face,e);for(int edge:edges){edge_faces[edge].push_back(face);const Entity*c=edge_curve(edge,e);std::string ck=c?c->kind:"UNKNOWN_CURVE";curve_hist[ck]++;if(ck=="UNKNOWN_CURVE")unknown_curves++;}const Entity*s=face_surface(face,e);std::string sk=s?s->kind:"UNKNOWN_SURFACE";surface_hist[sk]++;int bounds=0;for(int ref:e.at(face).refs){auto k=kind(ref,e);if(k=="FACE_BOUND"||k=="FACE_OUTER_BOUND")bounds++;}std::set<int>unique(edges.begin(),edges.end());std::string base=sk+"|b="+std::to_string(std::min(bounds,4))+"|d="+std::to_string(std::min<int>(unique.size(),12));labels[face]=base+"|p="+(s?parameter(*s,part_scale,false):"");family_labels[face]=base+"|p="+(s?parameter(*s,part_scale,true):"");}
  Adjacency adj,fadj;for(int face:faces){adj[face]={};fadj[face]={};}int shared=0,boundary=0,seams=0;for(const auto&[edge,attached]:edge_faces){std::set<int>set_faces(attached.begin(),attached.end());std::vector<int>unique(set_faces.begin(),set_faces.end());const Entity*c=edge_curve(edge,e);std::string ck=c?c->kind:"UNKNOWN_CURVE";std::string normal=ck+"|p="+(c?parameter(*c,part_scale,false):"");std::string family=ck+"|p="+(c?parameter(*c,part_scale,true):"");if(unique.size()==1){if(attached.size()>1){seams++;adj[unique[0]].push_back({unique[0],normal+"|SEAM"});fadj[unique[0]].push_back({unique[0],family+"|SEAM"});}else boundary++;}for(std::size_t i=0;i<unique.size();++i)for(std::size_t j=i+1;j<unique.size();++j){adj[unique[i]].push_back({unique[j],normal});adj[unique[j]].push_back({unique[i],normal});fadj[unique[i]].push_back({unique[j],family});fadj[unique[j]].push_back({unique[i],family});shared++;}}
  GraphDescriptor result;for(const auto&k:{"ADVANCED_FACE","EDGE_CURVE","ORIENTED_EDGE","VERTEX_POINT","EDGE_LOOP","FACE_BOUND","FACE_OUTER_BOUND","CLOSED_SHELL"})result.counts[k]=all_counts[k];result.surface_histogram=surface_hist;result.curve_histogram=curve_hist;result.wl_histogram=wl(labels,adj,iterations);result.wl_family_histogram=wl(family_labels,fadj,iterations);auto p=points(ids,e);result.distance_histogram=distance_hist(p);result.graph={{"nodes",static_cast<int>(faces.size())},{"shared_edges",shared},{"boundary_edges",boundary},{"seam_edges",seams},{"connected_components",components(adj)},{"vertex_points",static_cast<int>(p.size())},{"unknown_surface_uses",surface_hist["UNKNOWN_SURFACE"]},{"unknown_curve_uses",unknown_curves}};return{label(e,solid),result};
}

}  // namespace mbd
