cmake_minimum_required(VERSION 3.21)
project(dcc_capcut_qt_probe VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 6.2 REQUIRED COMPONENTS Core Gui Network)
add_library(dcc_capcut_probe MODULE probe.cpp)
target_link_libraries(dcc_capcut_probe PRIVATE Qt6::Core Qt6::Gui Qt6::Network)
set_target_properties(dcc_capcut_probe PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/generic"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/generic")
install(TARGETS dcc_capcut_probe LIBRARY DESTINATION generic RUNTIME DESTINATION generic)
add_executable(probe_fixture fixture.cpp)
target_link_libraries(probe_fixture PRIVATE Qt6::Core Qt6::Gui)
