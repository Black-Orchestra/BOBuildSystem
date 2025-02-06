cmake_minimum_required(VERSION 3.29)
project(build_commands_bot)

set(CMAKE_CXX_STANDARD 23)

include(CMakePrintHelpers)

include(CheckIPOSupported)
check_ipo_supported(RESULT BO_IPO_SUPPORTED OUTPUT BO_IPO_ERROR)

if (BO_IPO_SUPPORTED)
    message(STATUS "IPO / LTO enabled: ${BO_IPO_SUPPORTED}")
else ()
    message(STATUS "IPO / LTO not supported: ${BO_IPO_ERROR}")
endif ()

if (WIN32)
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
    cmake_print_variables(CMAKE_LIBRARY_OUTPUT_DIRECTORY)
    cmake_print_variables(CMAKE_RUNTIME_OUTPUT_DIRECTORY)
endif ()

include(cmake/dpp.cmake)
include(cmake/uuid_v4.cmake)

find_package(
    spdlog
    CONFIG
    REQUIRED
)

find_package(
    glaze
    CONFIG
    REQUIRED
)

find_package(
    openssl
    CONFIG
    REQUIRED
)

find_package(
    Boost
    CONFIG
    REQUIRED
    COMPONENTS
    asio
    cobalt
    process
    redis
    system
)

add_subdirectory(src)

# TODO: figure out smart way to build with different AVX/SSE versions
# dynamically based on what is available!

# TODO: C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
# - The above is required to make debug builds run with AddressSanitizer on MSVC.
# - Has to be set manually to toolchain in CLion currently.
# - Find a portable solution?
