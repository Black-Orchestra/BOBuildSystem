set(DPP_INSTALL 0)
set(RUN_LDCONFIG 0)
set(DPP_BUILD_TEST 0)
set(DPP_NO_VCPKG ON)
set(DPP_CORO ON)
set(DPP_FORMATTERS ON)
set(DPP_NO_CONAN ON)

add_subdirectory("${CMAKE_SOURCE_DIR}/submodules/dpp")
