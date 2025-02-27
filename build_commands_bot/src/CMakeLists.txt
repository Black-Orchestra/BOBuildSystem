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
    Boost::process
    Boost::redis
    Boost::system
    Boost::unordered
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

target_include_directories(
    build_commands_bot
    PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)
