#include <chrono>
#include <csignal>
#include <cstdlib>
#include <format>
#include <iostream>

#include <dpp/dpp.h>

#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/rotating_file_sink.h>

namespace
{

#if defined(WIN32) || defined(_WIN32) || defined(__WIN32) && !defined(__CYGWIN__)
#define BO_WINDOWS 1
#else
#define BO_WINDOWS 0
#endif

constexpr auto g_cmd_name_workshop_upload_beta = "workshop_upload_beta";

constexpr auto g_bo_guild_id = 934252753339953173;

std::shared_ptr<spdlog::logger> g_logger;

std::shared_ptr<dpp::cluster> g_bot;

std::string get_env_var(const std::string_view key)
{
#if BO_WINDOWS
    char* value;
    size_t len;
    const errno_t err = _dupenv_s(&value, &len, key.data());
    if (err)
    {
        throw std::runtime_error(std::format("_dupenv_s error: {}", err));
    }
    if (!value)
    {
        free(value); // TODO: This is not even needed?
        throw std::runtime_error(std::format("unable to get env var: {}", key));
    }
    const auto ret = std::string{value};
    free(value);
    return ret;
#else
    char* value = std::getenv(key.data());
    if (!value)
    {
        throw std::runtime_error(std::format("unable to get env var: {}", key));
    }
    return std::string{value};
#endif // BO_WINDOWS
}

std::string get_bot_token()
{
    return get_env_var("BO_DISCORD_BUILD_COMMAND_BOT_TOKEN");
}

volatile std::sig_atomic_t g_signal_status = 0;

} // namespace

void signal_handler(int signal)
{
    g_signal_status = signal;
}

void do_main()
{
    constexpr auto default_log_level = spdlog::level::info;

    spdlog::init_thread_pool(8192, 2);
    constexpr auto max_log_size = 1024 * 1024 * 10;
    auto stdout_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    auto rotating_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
        "bo_build_commands_bot.log", max_log_size, 3);
    const auto sinks = std::vector<spdlog::sink_ptr>{stdout_sink, rotating_sink};
    g_logger = std::make_shared<spdlog::async_logger>(
        "bo_build_commands_bot", sinks.cbegin(), sinks.cend(), spdlog::thread_pool(),
        spdlog::async_overflow_policy::overrun_oldest);
    spdlog::register_logger(g_logger);
    g_logger->set_level(default_log_level);
    g_logger->set_pattern("[%Y-%m-%d %H:%M:%S.%e%z] [%n] [%^%l%$] [th#%t]: %v");

    const auto bot_token = get_bot_token();
    g_bot = std::make_shared<dpp::cluster>(bot_token);

    g_bot->on_log(
        [](const dpp::log_t& event)
        {
            switch (event.severity)
            {
                case dpp::ll_trace:
                    g_logger->trace("{}", event.message);
                    break;
                case dpp::ll_debug:
                    g_logger->debug("{}", event.message);
                    break;
                case dpp::ll_info:
                    g_logger->info("{}", event.message);
                    break;
                case dpp::ll_warning:
                    g_logger->warn("{}", event.message);
                    break;
                case dpp::ll_error:
                    g_logger->error("{}", event.message);
                    break;
                case dpp::ll_critical:
                default:
                    g_logger->critical("{}", event.message);
                    break;
            }
        });

    g_bot->on_slashcommand(
        [](const dpp::slashcommand_t& event) -> dpp::task<void>
        {
            if (event.command.get_command_name() == g_cmd_name_workshop_upload_beta)
            {

            }

            co_return;
        });

    g_bot->on_ready(
        [](const dpp::ready_t& event)
        {
            if (dpp::run_once<struct register_bot_commands>())
            {
            }

            g_logger->info("bot is ready and initialized");
        });

    g_bot->start(dpp::st_return);

    constexpr auto sleep = std::chrono::milliseconds(100);
    while (g_signal_status == 0)
    {
        std::this_thread::sleep_for(sleep);
    }

    g_logger->info("exiting");
    g_bot->shutdown();
}

int main()
{
    try
    {
        std::signal(SIGINT, &signal_handler);
        std::signal(SIGTERM, &signal_handler);
#if !BO_WINDOWS
        std::signal(SIGHUP, &signal_handler);
#endif // !BO_WINDOWS

        do_main();

        return EXIT_SUCCESS;
    }
    catch (const std::exception& ex)
    {
        std::cout << std::format("unhandled exception: {}\n", ex.what());
    }
    catch (...)
    {
        std::cout << "unhandled error\n";
    }

    return EXIT_FAILURE;
}
