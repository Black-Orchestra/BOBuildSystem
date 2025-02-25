#ifndef BUILD_COMMANDS_BOT_BOBUILD_HPP
#define BUILD_COMMANDS_BOT_BOBUILD_HPP

#pragma once

#if defined(WIN32) || defined(_WIN32) || defined(__WIN32) && !defined(__CYGWIN__)
#define BO_WINDOWS 1
#else
#define BO_WINDOWS 0
#endif

namespace bo
{

} // bo

#endif // BUILD_COMMANDS_BOT_BOBUILD_HPP
