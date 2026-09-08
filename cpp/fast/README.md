# mbd_fast

`mbd_fast` is the standalone fast grouping kernel. It accepts precomputed part
features and returns deterministic complete-link group assignments. It has no
dependency on OpenCASCADE, STEP parsing, JSON, Python, or the rigid verifier.

## Add directly to another CMake project

```cmake
add_subdirectory(path/to/mbd_fast)
target_link_libraries(your_target PRIVATE mbd::fast)
```

```cpp
#include <mbd_fast/fast.hpp>

std::vector<mbd::fast::PartFeatures> parts = load_features();
const mbd::fast::GroupingResult result = mbd::fast::group(parts);
```

`PartFeatures` is the integration contract. The caller supplies exact mass
properties and graph histograms using its own model or file reader. The
algorithm does not inspect CAD files.

`<mbd_fast/topology.hpp>` additionally accepts kernel-neutral `PartTopology`
data and computes the graph descriptor entirely in memory. Hosts using OCCT
shapes can use the sibling [occt_fast adapter](../occt_fast/README.md) to extract
features and classify bodies directly without STEP serialization.
