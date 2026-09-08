#pragma once
#include <mbd_fast/fast.hpp>
#include <TopoDS_Shape.hxx>

namespace mbd { namespace occt_fast {

// Lower-level interface for caching features and testing against the STEP
// reference. Host code only needing classifications can use classifier.hpp.
fast::ExactProperties exact_properties(const TopoDS_Shape& shape, int index = 0);
fast::PartFeatures describe(const TopoDS_Shape& shape, int wl_iterations = 3);

} }
