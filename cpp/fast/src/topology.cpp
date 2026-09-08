#include "mbd_fast/topology.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <set>
#include <sstream>
#include <stdexcept>

namespace mbd::fast {
namespace {
using Point = std::array<double, 3>;
using Adjacency = std::map<int, std::vector<std::pair<int, std::string>>>;
std::string gformat(double value){std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(6)<<std::defaultfloat<<value;return out.str();}
std::string parameter(const GeometryLabel&item,double part_scale,bool family){const auto& l=item.lengths;const auto& a=item.angles;double scale=family?std::max(std::abs(part_scale),1e-15):1.0;std::vector<std::string>tokens;for(double value:l){double magnitude=std::abs(value)/scale;if(magnitude<1e-15){tokens.push_back("L0");continue;}double rounded=std::nearbyint(std::log10(magnitude)*16)/16;if(rounded==0)rounded=0;tokens.push_back("L"+gformat(rounded));}for(double value:a){double rounded=std::nearbyint(value*360/std::acos(-1.0))/2;if(rounded==0)rounded=0;tokens.push_back("A"+gformat(rounded));}std::ostringstream out;for(std::size_t i=0;i<tokens.size();++i){if(i)out<<':';out<<tokens[i];}return out.str();}

constexpr std::array<std::uint64_t,8> IV{0x6a09e667f3bcc908ULL,0xbb67ae8584caa73bULL,0x3c6ef372fe94f82bULL,0xa54ff53a5f1d36f1ULL,0x510e527fade682d1ULL,0x9b05688c2b3e6c1fULL,0x1f83d9abfb41bd6bULL,0x5be0cd19137e2179ULL};
constexpr std::array<std::array<unsigned char,16>,12>SIGMA{{
{{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15}},{{14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3}},{{11,8,12,0,5,2,15,13,10,14,3,6,7,1,9,4}},{{7,9,3,1,13,12,11,14,2,6,5,10,4,0,15,8}},{{9,0,5,7,2,4,10,15,14,1,11,12,6,8,3,13}},{{2,12,6,10,0,11,8,3,4,13,7,5,15,14,1,9}},{{12,5,1,15,14,13,4,10,0,7,6,3,9,2,8,11}},{{13,11,7,14,12,1,3,9,5,0,15,4,8,6,2,10}},{{6,15,14,9,11,3,0,8,12,2,13,7,1,4,10,5}},{{10,2,8,4,7,6,1,5,15,11,9,14,3,12,13,0}},{{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15}},{{14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3}}}};
std::uint64_t rotr(std::uint64_t x,int n){return(x>>n)|(x<<(64-n));}
void mix(std::array<std::uint64_t,16>&v,int a,int b,int c,int d,std::uint64_t x,std::uint64_t y){v[a]=v[a]+v[b]+x;v[d]=rotr(v[d]^v[a],32);v[c]+=v[d];v[b]=rotr(v[b]^v[c],24);v[a]=v[a]+v[b]+y;v[d]=rotr(v[d]^v[a],16);v[c]+=v[d];v[b]=rotr(v[b]^v[c],63);}
void compress(std::array<std::uint64_t,8>&h,const unsigned char*block,std::uint64_t count,bool last){std::array<std::uint64_t,16>m{},v{};for(int i=0;i<16;++i)for(int j=0;j<8;++j)m[i]|=static_cast<std::uint64_t>(block[i*8+j])<<(8*j);for(int i=0;i<8;++i){v[i]=h[i];v[i+8]=IV[i];}v[12]^=count;if(last)v[14]=~v[14];for(int r=0;r<12;++r){const auto&s=SIGMA[r];mix(v,0,4,8,12,m[s[0]],m[s[1]]);mix(v,1,5,9,13,m[s[2]],m[s[3]]);mix(v,2,6,10,14,m[s[4]],m[s[5]]);mix(v,3,7,11,15,m[s[6]],m[s[7]]);mix(v,0,5,10,15,m[s[8]],m[s[9]]);mix(v,1,6,11,12,m[s[10]],m[s[11]]);mix(v,2,7,8,13,m[s[12]],m[s[13]]);mix(v,3,4,9,14,m[s[14]],m[s[15]]);}for(int i=0;i<8;++i)h[i]^=v[i]^v[i+8];}
std::string token(const std::string&input){constexpr int outlen=10;std::array<std::uint64_t,8>h=IV;h[0]^=0x01010000^outlen;std::uint64_t count=0;std::size_t offset=0;while(input.size()-offset>128){compress(h,reinterpret_cast<const unsigned char*>(input.data()+offset),count+=128,false);offset+=128;}std::array<unsigned char,128>last{};std::copy(input.begin()+static_cast<std::ptrdiff_t>(offset),input.end(),last.begin());count+=input.size()-offset;compress(h,last.data(),count,true);std::array<unsigned char,outlen>digest{};for(int i=0;i<outlen;++i)digest[i]=static_cast<unsigned char>(h[i/8]>>(8*(i%8)));std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto byte:digest)out<<std::setw(2)<<static_cast<int>(byte);return out.str();}

std::map<std::string,int> wl(const std::map<int,std::string>&node_labels,const Adjacency&adj,int iterations){std::map<int,std::string>labels;std::map<std::string,int>hist;for(const auto&[node,value]:node_labels){labels[node]=token("0|"+value);hist["0:"+labels[node]]++;}for(int level=1;level<=iterations;++level){std::map<int,std::string>next;for(const auto&[node,current]:labels){std::vector<std::string>neighbors;for(const auto&[other,edge]:adj.at(node))neighbors.push_back(edge+":"+labels.at(other));std::sort(neighbors.begin(),neighbors.end());std::ostringstream value;value<<current<<'|';for(std::size_t i=0;i<neighbors.size();++i){if(i)value<<'|';value<<neighbors[i];}next[node]=token(value.str());}labels=next;for(const auto&[_,value]:labels)hist[std::to_string(level)+":"+value]++;}return hist;}
double dist(const Point&a,const Point&b){return std::hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);}
std::vector<double> distance_hist(const std::vector<Point>&p,int bins=32){std::vector<double>h(bins);if(p.size()<2)return h;double diameter=0;for(std::size_t l=0;l<p.size();++l)for(std::size_t r=0;r<l;++r)diameter=std::max(diameter,dist(p[l],p[r]));if(diameter<1e-12)return h;for(std::size_t l=0;l<p.size();++l)for(std::size_t r=0;r<l;++r){double position=std::clamp(dist(p[l],p[r])/diameter*(bins-1),0.0,bins-1.0);int lower=static_cast<int>(std::floor(position)),upper=std::min(bins-1,lower+1);double fraction=position-lower;h[lower]+=1-fraction;h[upper]+=fraction;}double total=0;for(double v:h)total+=v;if(total==0)total=1;for(double&v:h)v/=total;return h;}
int components(const Adjacency&adj){std::set<int>remaining;for(const auto&[id,_]:adj)remaining.insert(id);int count=0;while(!remaining.empty()){++count;std::vector<int>stack{*remaining.begin()};remaining.erase(stack.back());while(!stack.empty()){int current=stack.back();stack.pop_back();for(const auto&[other,_]:adj.at(current))if(remaining.erase(other))stack.push_back(other);}}return count;}

} // namespace

GraphDescriptor describe_topology(const PartTopology& topology, int iterations, double part_scale) {
  if (iterations < 0 || !std::isfinite(part_scale) || part_scale <= 0)
    throw std::invalid_argument("invalid descriptor options");
  std::vector<int> faces;
  std::map<int,std::vector<int>> edge_faces;
  std::map<int,std::string> labels,family_labels;
  std::map<std::string,int> surface_hist,curve_hist;
  int unknown_curves=0;
  for (std::size_t i=0;i<topology.faces.size();++i) {
    const int face=static_cast<int>(i);
    faces.push_back(face);
    const auto& f=topology.faces[i];
    for (int edge:f.edge_uses) {
      const auto& curve=topology.edges.at(edge);
      edge_faces[edge].push_back(face);
      curve_hist[curve.kind]++;
      if (curve.kind=="UNKNOWN_CURVE") ++unknown_curves;
    }
    surface_hist[f.surface.kind]++;
    const std::set<int> unique(f.edge_uses.begin(),f.edge_uses.end());
    const auto base=f.surface.kind+"|b="+std::to_string(std::min(f.bounds,4))+"|d="+std::to_string(std::min<int>(static_cast<int>(unique.size()),12));
    labels[face]=base+"|p="+parameter(f.surface,part_scale,false);
    family_labels[face]=base+"|p="+parameter(f.surface,part_scale,true);
  }
  Adjacency adj,fadj;for(int face:faces){adj[face]={};fadj[face]={};}int shared=0,boundary=0,seams=0;for(const auto&[edge,attached]:edge_faces){std::set<int>set_faces(attached.begin(),attached.end());std::vector<int>unique(set_faces.begin(),set_faces.end());const GeometryLabel* c=&topology.edges.at(edge);std::string ck=c->kind;std::string normal=ck+"|p="+(c?parameter(*c,part_scale,false):"");std::string family=ck+"|p="+(c?parameter(*c,part_scale,true):"");if(unique.size()==1){if(attached.size()>1){seams++;adj[unique[0]].push_back({unique[0],normal+"|SEAM"});fadj[unique[0]].push_back({unique[0],family+"|SEAM"});}else boundary++;}for(std::size_t i=0;i<unique.size();++i)for(std::size_t j=i+1;j<unique.size();++j){adj[unique[i]].push_back({unique[j],normal});adj[unique[j]].push_back({unique[i],normal});fadj[unique[i]].push_back({unique[j],family});fadj[unique[j]].push_back({unique[i],family});shared++;}}

  std::set<Point> unique_points;
  for (auto p:topology.vertices) {
    for (auto& value:p) {
      if (!std::isfinite(value)) throw std::invalid_argument("non-finite vertex");
      value=std::round(value*1e10)/1e10;
    }
    unique_points.insert(p);
  }
  const std::vector<Point> p(unique_points.begin(),unique_points.end());
  GraphDescriptor result;
  for (const auto* k:{"ADVANCED_FACE","EDGE_CURVE","ORIENTED_EDGE","VERTEX_POINT","EDGE_LOOP","FACE_BOUND","FACE_OUTER_BOUND","CLOSED_SHELL"}) {
    const auto it=topology.counts.find(k);
    result.counts[k]=it==topology.counts.end()?0:it->second;
  }
  result.surface_histogram=surface_hist;
  result.curve_histogram=curve_hist;
  result.wl_histogram=wl(labels,adj,iterations);
  result.wl_family_histogram=wl(family_labels,fadj,iterations);
  result.distance_histogram=distance_hist(p);
  result.graph={{"nodes",static_cast<int>(faces.size())},{"shared_edges",shared},{"boundary_edges",boundary},{"seam_edges",seams},{"connected_components",components(adj)},{"vertex_points",static_cast<int>(p.size())},{"unknown_surface_uses",surface_hist["UNKNOWN_SURFACE"]},{"unknown_curve_uses",unknown_curves}};
  return result;
}
} // namespace mbd::fast
