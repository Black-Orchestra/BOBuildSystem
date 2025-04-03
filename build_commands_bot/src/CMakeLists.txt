include(FetchContent)

FetchContent_Declare(
    cmake_git_version_tracking
    GIT_REPOSITORY https://github.com/andrew-hardin/cmake-git-version-tracking.git
    GIT_TAG 6c0cb87edd029ddfb403a8e24577c144a03605a6
)
FetchContent_MakeAvailable(cmake_git_version_tracking)

add_executable(
    build_commands_bot
    main.cpp
)

if (${BO_IPO_SUPPORTED})
    message(STATUS "Enabling IPO/LTO for build_commands_bot")
    set_property(
        TARGET build_commands_bot
        PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE
    )
endif ()

target_compile_features(
    build_commands_bot
    PRIVATE
    cxx_std_23
)

target_compile_options(
    build_commands_bot
    PRIVATE
    ${BO_COMPILE_OPTIONS}
)

target_link_options(
    build_commands_bot
    PUBLIC
    ${BO_LINKER_OPTIONS}
)

target_include_directories(
    build_commands_bot
    PUBLIC
    ${CMAKE_SOURCE_DIR}/include/
)

set(
    BUILD_COMMANDS_BOT_LIBS
    Boost::asio
    Boost::cobalt
    Boost::date_time
    Boost::process
    Boost::redis
    Boost::system
    Boost::unordered
    cmake_git_version_tracking
    dpp
    glaze::glaze
    libpqxx::pqxx
    spdlog::spdlog
    uuid_v4::uuid_v4
)

if (${CMAKE_CXX_COMPILER_ID} STREQUAL "GNU")
    list(APPEND BUILD_COMMANDS_BOT_LIBS stdc++exp)
endif ()

cmake_print_variables(BUILD_COMMANDS_BOT_LIBS)

target_link_libraries(
    build_commands_bot
    PRIVATE
    ${BUILD_COMMANDS_BOT_LIBS}
)

target_compile_definitions(
    build_commands_bot
    PUBLIC
    DPP_CORO
)

# TODO: why's this here?
target_include_directories(
    build_commands_bot
    PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)
