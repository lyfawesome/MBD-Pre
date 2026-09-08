cmake_minimum_required(VERSION 3.20)
project(mbd_occt_fast VERSION 1.0.0 LANGUAGES CXX)

if(NOT TARGET mbd::fast)
  add_subdirectory(../fast ${CMAKE_CURRENT_BINARY_DIR}/fast)
endif()
find_package(OpenCASCADE REQUIRED COMPONENTS FoundationClasses ModelingData ModelingAlgorithms)

add_library(mbd_occt_fast STATIC src/classifier.cpp)
add_library(mbd::occt_fast ALIAS mbd_occt_fast)
target_compile_features(mbd_occt_fast PRIVATE cxx_std_20)
# The public API uses C++17-compatible value types. It does not impose C++20
# on host applications such as SimNova.
target_compile_features(mbd_occt_fast INTERFACE cxx_std_17)
target_include_directories(mbd_occt_fast PUBLIC include)
target_include_directories(mbd_occt_fast SYSTEM PUBLIC ${OpenCASCADE_INCLUDE_DIR})
target_link_libraries(mbd_occt_fast PRIVATE mbd::fast
  PUBLIC TKBRep TKTopAlgo TKG3d TKG2d TKGeomBase TKMath TKernel)
if(MSVC)
  target_compile_options(mbd_occt_fast PRIVATE /W4 /permissive-)
else()
  target_compile_options(mbd_occt_fast PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  include(CTest)
endif()
if(BUILD_TESTING)
  add_executable(mbd_occt_fast_tests tests/test_classifier.cpp)
  target_link_libraries(mbd_occt_fast_tests PRIVATE mbd::occt_fast TKPrim)
  set_target_properties(mbd_occt_fast_tests PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
  add_test(NAME mbd_occt_fast_tests COMMAND mbd_occt_fast_tests)
endif()
