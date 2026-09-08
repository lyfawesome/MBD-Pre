#pragma once

#include <TopoDS_Shape.hxx>
#include <cstddef>
#include <string>
#include <vector>

namespace mbd { namespace occt_fast {

// Shapes are shared, read-only snapshots. Do not mutate them concurrently.
// One item is one logical body, including all its located solid occurrences.
struct Body {
  std::string id;
  TopoDS_Shape shape;
};

enum class Mode { strict, family };
struct Options {
  Mode mode{Mode::strict};
  double threshold{0.12};
  double size_tolerance{0.03};
  int wl_iterations{3};
};

struct Diagnostic {
  std::string body_id;
  std::string message;
};

struct Result {
  // All valid bodies, sorted by stable ID, including singleton groups.
  std::vector<std::vector<std::string>> groups;
  std::vector<std::string> body_ids;
  // assignments/distances use body_ids order; group numbers start at one.
  std::vector<int> assignments;
  std::vector<std::vector<double>> distances;
  std::vector<Diagnostic> skipped;
};

// No filesystem, STEP serialization, subprocess, UI or global settings.
// Invalid options/empty or duplicate IDs throw invalid_argument.
// Invalid geometry is skipped with its ID and a diagnostic.
Result classify(const std::vector<Body>& bodies, const Options& options = {});

} } // namespace mbd::occt_fast
