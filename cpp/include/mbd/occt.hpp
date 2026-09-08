#pragma once

#include "mbd/fast.hpp"

#include <filesystem>
#include <vector>

namespace mbd {

std::vector<ExactProperties> inspect_and_normalize(
    const std::filesystem::path& source,
    const std::filesystem::path& normalized_dir);

}  // namespace mbd
