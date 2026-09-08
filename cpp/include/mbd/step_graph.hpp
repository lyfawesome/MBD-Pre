#pragma once

#include "mbd/fast.hpp"

#include <string>
#include <utility>

namespace mbd {

std::pair<std::string, GraphDescriptor> describe_normalized_step(
    const std::string& path, int wl_iterations = 3, double part_scale = 1.0);

}  // namespace mbd
