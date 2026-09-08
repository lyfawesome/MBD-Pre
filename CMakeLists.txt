cmake_minimum_required(VERSION 3.20)
project(mbd_geometry_cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)

find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(OpenCASCADE REQUIRED COMPONENTS FoundationClasses ModelingData ModelingAlgorithms
  Visualization ApplicationFramework DataExchange)
find_path(NLOHMANN_JSON_INCLUDE_DIR nlohmann/json.hpp
  HINTS C:/msys64/ucrt64/include /ucrt64/include)
if(NOT NLOHMANN_JSON_INCLUDE_DIR)
  message(FATAL_ERROR "nlohmann/json.hpp is required for the parity CLI")
endif()

add_subdirectory(cpp/fast)

add_library(mbd_geometry_cpp
  cpp/src/rigid.cpp
  cpp/src/step_graph.cpp
  cpp/src/occt.cpp
)
target_include_directories(mbd_geometry_cpp PUBLIC cpp/include)
target_include_directories(mbd_geometry_cpp PRIVATE ${OpenCASCADE_INCLUDE_DIR})
target_link_libraries(mbd_geometry_cpp PUBLIC mbd::fast
  TKDESTEP TKXSBase TKBRep TKTopAlgo TKG3d TKG2d TKGeomBase TKMath TKernel)
if(MSVC)
  target_compile_options(mbd_geometry_cpp PRIVATE /W4 /permissive-)
else()
  target_compile_options(mbd_geometry_cpp PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(mbd_geometry_cli cpp/src/cli.cpp)
target_include_directories(mbd_geometry_cli PRIVATE ${NLOHMANN_JSON_INCLUDE_DIR})
target_link_libraries(mbd_geometry_cli PRIVATE mbd_geometry_cpp)

enable_testing()
add_executable(mbd_geometry_tests cpp/tests/test_algorithms.cpp)
target_link_libraries(mbd_geometry_tests PRIVATE mbd_geometry_cpp)
add_test(NAME mbd_geometry_tests COMMAND mbd_geometry_tests)
add_test(
  NAME python_cpp_parity
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/scripts/check_cpp_parity.py
          $<TARGET_FILE:mbd_geometry_cli>
)
