#include "mbd/occt.hpp"

#include <BRepBndLib.hxx>
#include <BRepGProp.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GProp_PrincipalProps.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>

#include <algorithm>
#include <array>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace mbd {
namespace {

ExactProperties inspect(const TopoDS_Shape& solid, int index) {
  GProp_GProps volume, surface, linear;
  BRepGProp::VolumeProperties(solid, volume, 1e-9, false, false);
  BRepGProp::SurfaceProperties(solid, surface, 1e-9, false);
  BRepGProp::LinearProperties(solid, linear, true, false);
  Standard_Real first, second, third;
  volume.PrincipalProperties().Moments(first, second, third);
  std::array<double, 3> moments{first, second, third};
  std::sort(moments.begin(), moments.end(), std::greater<>());
  Bnd_Box box;
  BRepBndLib::AddOptimal(solid, box, false, false);
  Standard_Real xmin, ymin, zmin, xmax, ymax, zmax;
  box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
  std::array<double, 3> bbox{std::abs(xmax - xmin), std::abs(ymax - ymin), std::abs(zmax - zmin)};
  std::sort(bbox.begin(), bbox.end(), std::greater<>());
  ExactProperties result;
  result.index = index;
  result.volume = volume.Mass();
  result.area = surface.Mass();
  // DRAW's `lprops shape -full`, used by the Python baseline, visits both
  // edge orientations held by a closed solid. Match that published baseline.
  result.edge_length = 2.0 * linear.Mass();
  result.moments = moments;
  return result;
}

void write_step(const TopoDS_Shape& shape, const std::filesystem::path& path) {
  STEPControl_Writer writer;
  if (writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone)
    throw std::runtime_error("OCCT failed to transfer normalized solid");
  if (writer.Write(path.string().c_str()) != IFSelect_RetDone)
    throw std::runtime_error("OCCT failed to write normalized STEP: " + path.string());
}

}  // namespace

std::vector<ExactProperties> inspect_and_normalize(
    const std::filesystem::path& source,
    const std::filesystem::path& normalized_dir) {
  if (!std::filesystem::is_regular_file(source))
    throw std::runtime_error("STEP source does not exist: " + source.string());
  std::filesystem::create_directories(normalized_dir);
  STEPControl_Reader reader;
  if (reader.ReadFile(source.string().c_str()) != IFSelect_RetDone)
    throw std::runtime_error("OCCT failed to read STEP: " + source.string());
  if (reader.TransferRoots() <= 0) throw std::runtime_error("OCCT transferred no STEP roots");
  const TopoDS_Shape assembly = reader.OneShape();
  std::vector<ExactProperties> result;
  int index = 0;
  for (TopExp_Explorer explorer(assembly, TopAbs_SOLID); explorer.More(); explorer.Next()) {
    const TopoDS_Shape solid = explorer.Current();
    ++index;
    char filename[32];
    std::snprintf(filename, sizeof(filename), "part_%04d.step", index);
    write_step(solid, normalized_dir / filename);
    result.push_back(inspect(solid, index));
  }
  if (result.empty()) throw std::runtime_error("STEP assembly contains no solids");
  return result;
}

}  // namespace mbd
