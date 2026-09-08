cmake_minimum_required(VERSION 3.20)

# This directory is intentionally a self-contained CMake project. Consumers can
# use add_subdirectory(path/to/cpp/fast) without configuring OCCT or the rest of
# the geometry encoder.
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  project(mbd_fast VERSION 1.0.0 LANGUAGES CXX)
  include(CTest)
endif()

add_library(mbd_fast src/fast.cpp)
add_library(mbd::fast ALIAS mbd_fast)
target_compile_features(mbd_fast PUBLIC cxx_std_20)
target_include_directories(mbd_fast
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
set_target_properties(mbd_fast PROPERTIES
  VERSION 1.0.0
  SOVERSION 1
  WINDOWS_EXPORT_ALL_SYMBOLS ON
  EXPORT_NAME fast)

if(MSVC)
  target_compile_options(mbd_fast PRIVATE /W4 /permissive-)
else()
  target_compile_options(mbd_fast PRIVATE -Wall -Wextra -Wpedantic)
endif()

set(_MBD_FAST_STANDALONE OFF)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  set(_MBD_FAST_STANDALONE ON)
endif()
option(MBD_FAST_BUILD_TESTS "Build standalone mbd_fast tests" ${_MBD_FAST_STANDALONE})
option(MBD_FAST_BUILD_EXAMPLE "Build standalone mbd_fast example" ${_MBD_FAST_STANDALONE})

if(MBD_FAST_BUILD_TESTS)
  add_executable(mbd_fast_tests tests/test_fast.cpp)
  target_link_libraries(mbd_fast_tests PRIVATE mbd::fast)
  add_test(NAME mbd_fast_tests COMMAND mbd_fast_tests)
endif()

if(MBD_FAST_BUILD_EXAMPLE)
  add_executable(mbd_fast_example examples/basic.cpp)
  target_link_libraries(mbd_fast_example PRIVATE mbd::fast)
endif()

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
install(TARGETS mbd_fast EXPORT mbd_fastTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT mbd_fastTargets
  FILE mbd_fastTargets.cmake
  NAMESPACE mbd::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/mbd_fast)
configure_package_config_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/mbd_fastConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/mbd_fastConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/mbd_fast)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/mbd_fastConfigVersion.cmake
  VERSION 1.0.0
  COMPATIBILITY SameMajorVersion)
install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/mbd_fastConfig.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/mbd_fastConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/mbd_fast)
