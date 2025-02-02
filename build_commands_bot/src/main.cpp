#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <format>
#include <iostream>
#include <memory>
#include <string_view>
#include <thread>

#if defined(WIN32) || defined(_WIN32) || defined(__WIN32) && !defined(__CYGWIN__)
#define BO_WINDOWS 1

#include <SDKDDKVer.h> // Silence "Please define _WIN32_WINNT or _WIN32_WINDOWS appropriately".

#else
#define BO_WINDOWS 0
#endif

#include <boost/asio/as_tuple.hpp>
#include <boost/asio/co_spawn.hpp>
#include <boost/cobalt.hpp>
#include <boost/asio/detached.hpp>
#include <boost/asio/use_future.hpp>
#include <boost/asio/experimental/concurrent_channel.hpp>
// #include <boost/asio/experimental/use_promise.hpp> TODO: even including this errors?
#include <boost/asio/io_context.hpp>
#include <boost/asio/signal_set.hpp>
#include <boost/asio/steady_timer.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <boost/redis/config.hpp>

#include <dpp/dpp.h>

#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/rotating_file_sink.h>

#include "taskiq.hpp"

namespace
{

namespace chrono = std::chrono;
namespace asio = boost::asio;
namespace redis = boost::redis;
namespace cobalt = boost::cobalt;

using boost::asio::experimental::concurrent_channel;

enum class MessageType: std::uint8_t
{
    WorkshopUploadBeta,
};

// TODO: include explicit executor type here?
// TODO: currently this channel only send/receives the message type as
//   our messages are always the same and we don't need any argument handling.
using MessageChannel = concurrent_channel<void(boost::system::error_code, MessageType)>;

constexpr auto g_cmd_name_sws_upload_beta = "workshop_upload_beta";
constexpr auto g_cmd_name_sws_get_info = "workshop_info";

constexpr auto g_desc_max_len = 100U;
constexpr auto g_cmd_desc_sws_upload_beta
    = "Tag the latest of commit of each repo and upload content to BO Beta Steam Workshop";
constexpr auto g_cmd_desc_sws_get_info
    = "Display metadata of current latest Workshop upload.";

static_assert(std::string_view{g_cmd_desc_sws_upload_beta}.size() <= g_desc_max_len,
              "g_cmd_desc_sws_upload_beta too long");
static_assert(std::string_view{g_cmd_desc_sws_get_info}.size() <= g_desc_max_len,
              "g_cmd_desc_sws_get_info too long");

constexpr std::uint64_t g_bo_guild_id = 934252753339953173;

std::shared_ptr<spdlog::logger> g_logger;

std::shared_ptr<dpp::cluster> g_bot;

#ifndef NDEBUG

bool debugger_present()
{
#if BO_WINDOWS
    return IsDebuggerPresent();
#else
    // TODO: Linux version?
    return false;
#endif // BO_WINDOWS
}

#else

constexpr bool debugger_present()
{
    return false;
}

#endif // NDEBUG

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

auto send_workshop_upload_beta_msg(
    std::shared_ptr<MessageChannel> msg_channel
) -> asio::awaitable<int>
{
    g_logger->info("send_workshop_upload_beta_msg running in asio::awaitable");

    co_await msg_channel->async_send(
        boost::system::error_code{},
        MessageType::WorkshopUploadBeta,
        asio::use_awaitable);

    co_return 1;
}

// TODO: THIS IS THE RIGHT WAY TO CO-OP DPP AND ASIO/COBALT!
auto send_workshop_upload_beta_msg_cobalt(
    std::shared_ptr<MessageChannel> msg_channel
) -> cobalt::task<int>
{
    // 1. Check if task lock exists.

    g_logger->info("send_workshop_upload_beta_msg running in cobalt::task");
    // auto exec = co_await cobalt::this_coro::executor;

    co_await msg_channel->async_send(
        boost::system::error_code{},
        MessageType::WorkshopUploadBeta,
        cobalt::use_op
    );

    g_logger->info("sent");

    asio::steady_timer test_timer{msg_channel->get_executor()};
    test_timer.expires_after(chrono::seconds(10));
    co_await test_timer.async_wait();

    co_return 1;
}

auto workshop_upload_beta_task(
    std::shared_ptr<MessageChannel> msg_channel
) -> dpp::task<int>
{
    g_logger->info("workshop_upload_beta_task running in dpp::task");

    // Offload work to ASIO thread.
    auto deferred_op = asio::co_spawn(
        msg_channel->get_executor(),
        send_workshop_upload_beta_msg(msg_channel),
        asio::deferred);

    auto future = std::move(deferred_op)(asio::use_future);

    asio::steady_timer test_timer{msg_channel->get_executor()};
    test_timer.expires_after(chrono::seconds(5));
    test_timer.async_wait();

    const int result = future.get();
    co_return result;
}

auto cobalt_task_test() -> cobalt::task<void>
{
    g_logger->info("cobalt_task_test running in cobalt::task");
    co_return;
}

void bot_main(std::shared_ptr<MessageChannel> msg_channel)
{
    const auto redis_url = get_env_var("BO_REDIS_URL");
    const auto postgres_url = get_env_var("BO_POSTGRES_URL");
    const auto bot_token = get_env_var("BO_DISCORD_BUILD_COMMAND_BOT_TOKEN");

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
        [&msg_channel](const dpp::slashcommand_t& event) -> dpp::task<void>
        {
            const auto cmd_name = event.command.get_command_name();
            g_logger->info("processing command: {}", cmd_name);

            if (cmd_name == g_cmd_name_sws_upload_beta)
            {
                // TODO:
                // - Check if current tag exists in repos.
                //   - Git repo: libgit2. (TODO: this might be too cumbersome!)
                //   - Hg repos: asio process.
                //   - If exists already IN ANY -> error.
                // - Tag it in all repos.
                // - Fire off taskiq task!
                //   - Publish it to redis.

                // TODO: so I need to fire up a dpp task or something, that I can
                //   co_await on, to prevent blocking dpp. Inside that dpp task, I
                //   I will also need to wait for the result of the asio task!

                // DPP task.
                // const auto y = co_await workshop_upload_beta_task(msg_channel);

//                asio::co_spawn(
//                    msg_channel->get_executor(),
//                    send_workshop_upload_beta_msg(msg_channel),
//                    asio::detached);

//                asio::co_spawn(
//                    msg_channel->get_executor(),
//                    send_workshop_upload_beta_msg(msg_channel),
//                    cobalt::use_op);

                auto f = cobalt::spawn(
                    msg_channel->get_executor(),
                    send_workshop_upload_beta_msg_cobalt(msg_channel),
                    asio::use_future
                );
                const auto x = f.get();
                g_logger->info("x={}", x);

                // co_await send_workshop_upload_beta_msg_cobalt(msg_channel);

                // Cobalt task.
                // co_await cobalt_task_test();

                // TODO: we should probably wait to hear back from the
                //   Python job here!
            }
            else if (cmd_name == g_cmd_name_sws_get_info)
            {
                g_logger->info("fetching SWS metadata");
            }
            else
            {
                g_logger->error("unknown command: {}", cmd_name);
            }

            co_return;
        });

    g_bot->on_ready(
        [](const dpp::ready_t& event) -> dpp::task<void>
        {
            constexpr auto bo_guild = dpp::snowflake{g_bo_guild_id};
            for (const auto& guild: event.guilds)
            {
                if (guild != bo_guild)
                {
                    std::string guild_name = "UNKNOWN GUILD NAME";

                    const auto result = co_await event.owner->co_guild_get(guild);
                    if (!result.is_error())
                    {
                        const auto guild_obj = result.get<dpp::guild>();
                        guild_name = guild_obj.name;
                    }
                    else
                    {
                        g_logger->error("co_guild_get error: {}",
                                        result.get_error().human_readable);
                    }

                    g_logger->info("leaving forbidden guild: {}: {}", guild.str(), guild_name);
                    co_await event.owner->co_current_user_leave_guild(guild);
                }
            }

            if (dpp::run_once<struct register_bot_commands>())
            {
                dpp::slashcommand sws_upload_cmd{
                    g_cmd_name_sws_upload_beta, g_cmd_desc_sws_upload_beta, g_bot->me.id};
                dpp::slashcommand sws_get_info{
                    g_cmd_name_sws_get_info, g_cmd_desc_sws_get_info, g_bot->me.id};

                g_bot->guild_bulk_command_create(
                    {
                        sws_upload_cmd,
                        sws_get_info,
                    },
                    g_bo_guild_id);
            }

            g_logger->info("bot is ready and initialized");

            co_return;
        });

    g_bot->start(dpp::st_wait);

    // constexpr auto sleep = chrono::milliseconds(100);
    // while (g_signal_status == 0)
    // {
    //     std::this_thread::sleep_for(sleep);
    // }
    // g_bot->shutdown();
}

auto co_handle_workshop_upload_beta() -> asio::awaitable<void>
{
    // TODO: post to Redis!

    co_return;
}

auto co_main(
    redis::config cfg,
    std::shared_ptr<MessageChannel> msg_channel
) -> asio::awaitable<void>
{
    // TODO: process redis shit here.
    // - while running:
    // - get message from "queue"

    // TODO: create a new connection every time we get a new message. The rate at
    //   which we receive them is so low, it shouldn't matter here.

    while (true)
    {
        const auto [ec, msg_type] = co_await msg_channel->async_receive(
            asio::as_tuple(asio::use_awaitable));

        const auto mt = static_cast<std::underlying_type<MessageType>::type>(msg_type);

        g_logger->info("got message: {}", mt);

        if (!ec)
        {
            switch (msg_type)
            {
                case MessageType::WorkshopUploadBeta:
                    co_await co_handle_workshop_upload_beta();
                    break;
                default:
                    g_logger->error("invalid MessageType: {}", mt);
            }
        }
        else if (ec.value() == asio::error::eof)
        {
            g_logger->info("co_main: {}: {}", ec.value(), ec.message());
            break;
        }
        else
        {
            g_logger->error("co_main error: {}: {}", ec.value(), ec.message());
        }
    }
}

} // namespace

int main()
{
    try
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

        redis::config redis_cfg;
        asio::io_context ioc{BOOST_ASIO_CONCURRENCY_HINT_1};
        // TODO: what's the actual plan with this?
        //   - In redis "broker" thread, wait for this timer?
        //   - When cancel_one is called on the timer, send the message!?
        //   - What about synchronized access to the message data??
        // asio::steady_timer msg_timer{ioc.get_executor()};

        constexpr std::size_t msg_channel_size = 512;
        // MessageChannel msg_channel{ioc.get_executor(), msg_channel_size};
        auto msg_channel = std::make_shared<MessageChannel>(ioc.get_executor(), msg_channel_size);

        std::thread bot_thread(bot_main, msg_channel);

        asio::co_spawn(ioc, co_main(redis_cfg, msg_channel), [](std::exception_ptr e)
        {
            if (e)
            {
                std::rethrow_exception(e);
            }
        });

        asio::signal_set signals{
            ioc,
            SIGINT,
            SIGTERM,
#if !BO_WINDOWS
            SIGHUP
#endif // !BO_WINDOWS
        };
        signals.async_wait(
            [&](auto, auto)
            {
                g_bot->shutdown();
                msg_channel->cancel();
                ioc.stop();
            });

        // TODO: is there any need to make this multi-threaded too?
        ioc.run();

        bot_thread.join();

        g_logger->info("exiting");

        return EXIT_SUCCESS;
    }
    catch (const std::exception& ex)
    {
        std::cout << std::format("unhandled exception: {}\n", ex.what());
        if (debugger_present())
        {
            throw;
        }
    }
    catch (...)
    {
        std::cout << "unhandled error\n";
        if (debugger_present())
        {
            throw;
        }
    }

    return EXIT_FAILURE;
}
