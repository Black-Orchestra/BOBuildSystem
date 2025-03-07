vcpkg_from_github(
    OUT_SOURCE_PATH SOURCE_PATH
    REPO boostorg/process
    REF boost-${VERSION}
    SHA512 a084c71effdd591b83a7fbff85bdea925da1436dc452267ceafd0f7bd875dcd9611cd28a92c06548e9130bb596703ea05932cd94063724cfecf6d861cceebe21
    HEAD_REF master
    PATCHES
    processv2.patch
)

set(FEATURE_OPTIONS "")
boost_configure_and_install(
    SOURCE_PATH "${SOURCE_PATH}"
    OPTIONS ${FEATURE_OPTIONS}
)
