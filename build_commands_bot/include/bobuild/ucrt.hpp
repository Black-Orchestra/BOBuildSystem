#ifndef BUILD_COMMANDS_BOT_UCRT_HPP
#define BUILD_COMMANDS_BOT_UCRT_HPP

#pragma once

#if BO_WINDOWS

#include <array>
#include <expected>

#define UNICODE

#include <windows.h>

#include "bobuild/bobuild.hpp"

#pragma comment(lib, "version.lib")
#pragma comment(lib, "Kernel32.lib")

namespace bo
{

struct UCRTVersion
{
    std::array<std::uint16_t, 4> FileVersion;
    std::array<std::uint16_t, 4> ProductVersion;
};

inline std::expected<UCRTVersion, HRESULT> GetUCRTVersion()
{
#ifdef _DEBUG
    static constexpr LPCSTR DllName = "ucrtbased.dll";
#else
    static constexpr LPCSTR DllName = "ucrtbase.dll";
#endif

    const HMODULE ucrt{GetModuleHandle(DllName)};
    if (!ucrt)
    {
        return std::unexpected(HRESULT_FROM_WIN32(GetLastError()));
    }

    std::wstring path;
    path.resize_and_overwrite(_MAX_PATH, [ucrt](wchar_t* ptr, const std::size_t size)
    {
        return GetModuleFileName(ucrt, reinterpret_cast<LPSTR>(ptr), static_cast<DWORD>(size));
    });

    const DWORD versionInfoSize = GetFileVersionInfoSize(
        reinterpret_cast<LPCSTR>(path.c_str()),
        nullptr
    );
    if (!versionInfoSize)
    {
        return std::unexpected(HRESULT_FROM_WIN32(GetLastError()));
    }

    std::vector<std::byte> versionInfo(versionInfoSize);

    if (!GetFileVersionInfo(
        reinterpret_cast<LPCSTR>(path.data()),
        0,
        static_cast<DWORD>(versionInfo.size()),
        versionInfo.data()))
    {
        return std::unexpected(HRESULT_FROM_WIN32(GetLastError()));
    }

    VS_FIXEDFILEINFO* fixedFileInfo;
    if (!VerQueryValue(
        versionInfo.data(),
        TEXT("\\"),
        reinterpret_cast<void**>(&fixedFileInfo),
        nullptr))
    {
        return std::unexpected(HRESULT_FROM_WIN32(GetLastError()));
    }

    return UCRTVersion{
        {HIWORD(fixedFileInfo->dwFileVersionMS),    LOWORD(fixedFileInfo->dwFileVersionMS),
            HIWORD(fixedFileInfo->dwFileVersionLS),    LOWORD(fixedFileInfo->dwFileVersionLS)},
        {HIWORD(fixedFileInfo->dwProductVersionMS), LOWORD(fixedFileInfo->dwProductVersionMS),
            HIWORD(fixedFileInfo->dwProductVersionLS), LOWORD(fixedFileInfo->dwProductVersionLS)}
    };
}

} // namespace bo

#endif // BO_WINDOWS

#endif // BUILD_COMMANDS_BOT_UCRT_HPP
