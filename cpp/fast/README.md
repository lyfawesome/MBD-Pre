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
