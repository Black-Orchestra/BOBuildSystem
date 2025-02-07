#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <format>
#include <iostream>
#include <memory>
#include <optional>
#include <random>
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
#include <boost/asio/experimental/channel.hpp>
#include <boost/asio/experimental/concurrent_channel.hpp>
#include <boost/asio/io_context.hpp>
#include <boost/asio/redirect_error.hpp>
#include <boost/asio/signal_set.hpp>
#include <boost/asio/steady_timer.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <boost/asio/use_future.hpp>
#include <boost/cobalt.hpp>
#include <boost/process/v2/process.hpp>
#include <boost/redis/config.hpp>
#include <boost/redis/connection.hpp>
#include <boost/redis/request.hpp>
#include <boost/redis/response.hpp>
#include <boost/redis/src.hpp>

#include <dpp/dpp.h>

#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/rotating_file_sink.h>

#include <uuid_v4.h>

#include <glaze/glaze.hpp>

#include "taskiq.hpp"

namespace
{

namespace chrono = std::chrono;
namespace asio = boost::asio;
namespace redis = boost::redis;
namespace cobalt = boost::cobalt;
namespace process = boost::process::v2;

using boost::asio::experimental::channel;
using boost::asio::experimental::concurrent_channel;

enum class MessageType: std::uint8_t
{
    WorkshopUploadBeta,
};

// TODO: passed into MessageChannel message to provide a one way
//  single-producer, single-consumer return channel for the job result/error.
using MessageResponseChannel = channel<void(boost::system::error_code, std::string)>;
// TODO: include explicit executor type here?
using MessageChannel = concurrent_channel<
    void(boost::system::error_code, MessageType, MessageResponseChannel*)>;

constexpr auto g_taskiq_redis_channel = "taskiq";
// Mirrored in Python bobuild/tasks.py.
constexpr auto g_taskiq_lock_timeout = 240 * 60;

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

#define THROW_IF_DEBUGGING()    \
if (debugger_present())         \
{                               \
    throw;                      \
}                               \


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

// TODO: THIS IS THE RIGHT WAY TO CO-OP DPP AND ASIO/COBALT!
auto send_workshop_upload_beta_msg_cobalt(
    std::shared_ptr<MessageChannel> msg_channel
) -> cobalt::task<boost::system::result<std::string>>
{
    auto ex = co_await cobalt::this_coro::executor;

    // TODO: workshop upload beta task runs in asio executor, we should
    //   somehow wait for responses/errors here, and propagate them to the DPP bot.
    //   1. Create a channel when we get here.
    //   2. Send that channel along with the message type.
    //   3. Wait for response, error or OK status, co_return them.
    MessageResponseChannel resp_channel{ex};

    g_logger->info("send_workshop_upload_beta_msg running in cobalt::task");

    co_await msg_channel->async_send(
        boost::system::error_code{},
        MessageType::WorkshopUploadBeta,
        &resp_channel,
        cobalt::use_op
    );

    g_logger->info("sent");

    asio::steady_timer test_timer{ex};
    test_timer.expires_after(chrono::seconds(10));
    co_await test_timer.async_wait();

    const auto [ec, resp] = co_await resp_channel.async_receive(
        asio::as_tuple(cobalt::use_op));

    if (ec)
    {
        co_return ec;
    }
    co_return resp;
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

                auto sws_future = cobalt::spawn(
                    msg_channel->get_executor(),
                    send_workshop_upload_beta_msg_cobalt(msg_channel),
                    asio::use_future
                );
                const boost::system::result<std::string> result = sws_future.get();
                if (result)
                {
                    g_logger->info("result={}", result.value());
                }
                else
                {
                    g_logger->error("result={}", result.error().message());
                }

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

auto co_handle_workshop_upload_beta(
    redis::config cfg
) -> asio::awaitable<boost::system::result<std::string>>
{
    auto ex = co_await asio::this_coro::executor;
    auto conn = redis::connection{ex};

    // 1. Check if task lock exists.
    redis::request lock_req;
    redis::response<bool> lock_resp; // TODO: what's the resp here?
    lock_req.push("SET", "key", taskiq::bo_build_lock_name, "EX", g_taskiq_lock_timeout, "NX", 1);
    const auto [lock_req_ec, _0] = co_await conn.async_exec(
        lock_req, lock_resp, asio::as_tuple(asio::use_awaitable));
    if (lock_req_ec)
    {
        // TODO: propagate error codes!
        throw std::runtime_error(std::format(
            "redis error: {}", lock_req_ec.message()));
    }

    auto msg = taskiq::make_bo_sws_upload_msg();
    UUIDv4::UUIDGenerator<std::mt19937_64> uuid_gen;
    UUIDv4::UUID uuid = uuid_gen.getUUID();
    msg.task_id = uuid.bytes();

    std::string msg_json{};
    const auto json_ec = glz::write_json(msg, msg_json);
    if (json_ec)
    {
        // TODO: propagate error codes!
        throw std::runtime_error(std::format(
            "glz::write_json error: {}", json_ec.custom_error_message));
    }

    redis::request pub_req;
    pub_req.push("PUBLISH", g_taskiq_redis_channel, msg_json);
    const auto [pub_req_ec, _1] = co_await conn.async_exec(
        pub_req, redis::ignore, asio::as_tuple(asio::use_awaitable));
    // TODO: check ec.

    conn.cancel();

    // TODO: actual error handling!
    co_return "OK?";
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
        const auto [ec, msg_type, resp_channel_ptr] = co_await msg_channel->async_receive(
            asio::as_tuple(asio::use_awaitable));

        const auto mt = static_cast<std::underlying_type<MessageType>::type>(msg_type);

        g_logger->info("got message: {}", mt);

        boost::system::result<std::string> job_result;
        boost::system::error_code job_error{};
        std::string job_result_value{};
        boost::system::error_code send_resp_ec{};
        if (!ec)
        {
            switch (msg_type)
            {
                case MessageType::WorkshopUploadBeta:
                    job_result = co_await co_handle_workshop_upload_beta(cfg);
                    job_error = job_result.error();
                    job_result_value = (job_result.has_value()) ? job_result.value() : "";
                    co_await resp_channel_ptr->async_send(
                        job_error,
                        job_result_value,
                        asio::redirect_error(send_resp_ec)
                    );
                    break;
                default:
                    g_logger->error("invalid MessageType: {}", mt);
            }

            if (send_resp_ec)
            {
                g_logger->error("async_send error: failed to send job result response: {}",
                                send_resp_ec.message());
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
    int rc = EXIT_SUCCESS;

    try
    {
#ifndef NDEBUG
        constexpr auto default_log_level = spdlog::level::debug;
#else
        constexpr auto default_log_level = spdlog::level::info;
#endif
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

        const auto stop = [&msg_channel, &ioc]
            (std::optional<boost::system::error_code> ec = std::nullopt,
             std::optional<int> signal = std::nullopt)
        {
            if (g_logger)
            {
                const auto estr = (ec) ? std::to_string(ec.value().value()) : "notset";
                const auto sstr = (signal) ? std::to_string(signal.value()) : "notset";
                g_logger->info("stopping, ec={}, sig={}", estr, sstr);
            }
            if (g_bot)
            {
                g_bot->shutdown();
            }
            if (msg_channel)
            {
                msg_channel->cancel();
            }
            ioc.stop();
        };

        std::exception_ptr bot_main_ex;
        std::thread bot_thread(
            [&bot_main_ex, &msg_channel, &stop]()
            {
                try
                {
                    bot_main(msg_channel);
                }
                catch (...)
                {
                    stop();
                    bot_main_ex = std::current_exception();
                }
            });

        asio::co_spawn(ioc, co_main(redis_cfg, msg_channel), [&stop](std::exception_ptr e)
        {
            if (e)
            {
                stop();
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
            [&stop](boost::system::error_code ec, int signal)
            {
                stop(ec, signal);
            });

        // TODO: is there any need to make this multi-threaded too?
        ioc.run();

        bot_thread.join();

        if (bot_main_ex)
        {
            std::rethrow_exception(bot_main_ex);
        }

        g_logger->info("exiting");
        rc = EXIT_SUCCESS;
    }
    catch (const std::exception& ex)
    {
        rc = EXIT_FAILURE;
        std::cout << std::format("unhandled exception: {}", ex.what()) << std::endl;
        THROW_IF_DEBUGGING();
    }
    catch (...)
    {
        rc = EXIT_FAILURE;
        std::cout << "unhandled error" << std::endl;
        THROW_IF_DEBUGGING();
    }

    if (g_logger)
    {
        g_logger->flush();
    }

    return rc;
}
