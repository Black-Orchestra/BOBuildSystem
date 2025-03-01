#ifndef BUILD_COMMANDS_BOT_REDIS_POOL_HPP
#define BUILD_COMMANDS_BOT_REDIS_POOL_HPP

#pragma once

#include <exception>
#include <memory>

#include <boost/asio/deadline_timer.hpp>
#include <boost/asio/detached.hpp>
#include <boost/asio/executor.hpp>
#include <boost/asio/placeholders.hpp>
#include <boost/bind/bind.hpp>
#include <boost/date_time/posix_time/posix_time_types.hpp>
#include <boost/redis.hpp>
#include <boost/system/system_error.hpp>
#include <boost/unordered/concurrent_flat_map.hpp>

#include "bobuild/bobuild.hpp"

namespace asio = boost::asio;

namespace bo::redis
{

template<typename ExecutorType = boost::asio::any_io_executor>
class ConnectionPool;

template<typename ExecutorType = boost::asio::any_io_executor>
class Connection
{
public:
    Connection(
        ConnectionPool<ExecutorType>& pool,
        std::shared_ptr<boost::redis::connection> conn_
    ) : conn(std::move(conn_)), m_pool(pool)
    {
    }

    ~Connection()
    {
        std::cerr << std::format("bye from: {}\n", fmt::ptr(this));
        close();
    }

    Connection(const Connection&) = delete;

    Connection(Connection&& other) noexcept
        : conn(std::move(other.conn)), m_pool(other.m_pool)
    {
    }

    Connection& operator=(const Connection&) = delete;

    Connection operator=(Connection&& other) noexcept
    {
        this->conn = std::move(other.conn);
        this->m_pool = std::move(other.m_pool);
    }

    // "Close" connection, i.e. return it to the pool.
    void close()
    {
        if (conn)
        {
            std::cerr << "got conn\n";

            std::cerr << "CLOSING CONN!" << std::endl;
            // std::cerr << std::stacktrace::current() << std::endl;
            // std::cerr << "-------------\n";
            m_pool.close_connection(conn);
            conn = nullptr;

        }
        else
        {
            std::cerr << "don't got conn\n";
        }
    }

    std::shared_ptr<boost::redis::connection> conn;

private:
    ConnectionPool<ExecutorType>& m_pool;
};

/**
 * Simple connection pool for Boost.Redis.
 *
 * TODO: periodic connection health checks?
 */
template<typename ExecutorType>
class ConnectionPool
{
    using PoolConnection = Connection<ExecutorType>;

public:
    ConnectionPool(
        boost::redis::config config,
        ExecutorType executor,
        std::size_t pool_size = 4,
        boost::posix_time::time_duration timer_interval = boost::posix_time::seconds{10}
    ) : m_pool{pool_size}, m_config{std::move(config)}, m_closed{false},
        m_timer{executor, timer_interval}, m_timer_interval{timer_interval}
    {
        for (auto i = 0; i < pool_size; ++i)
        {
            auto conn = std::make_shared<boost::redis::connection>(executor);
            std::cout << std::format("conn={}", fmt::ptr(&*conn)) << std::endl;
            // TODO: connection error callback?
            // conn->async_run(m_config, {}, asio::consign(asio::detached, conn));
            conn->async_run(
                m_config,
                boost::redis::logger{boost::redis::logger::level::err},
                [conn](boost::system::error_code conn_ec)
                {
                    std::cout << "conn async_run completion!" << std::endl;

                    if (conn)
                    {
                        conn->cancel();
                    }

                    if (conn_ec)
                    {
                        throw std::runtime_error(
                            std::format("redis connection async_run error: {}", conn_ec.message()));
                    }
                }
            );
            // TODO: check if exists, error handling?
            m_pool.emplace(conn, false);
        }

        m_timer.async_wait(
            boost::bind(
                &ConnectionPool::maintenance,
                this,
                boost::asio::placeholders::error
            )
        );
    }

    ~ConnectionPool()
    {
        cancel();
    }

    ConnectionPool(const ConnectionPool&) = delete;

    ConnectionPool(ConnectionPool&&) noexcept = delete;

    ConnectionPool& operator=(const ConnectionPool&) = delete;

    ConnectionPool operator=(ConnectionPool&&) noexcept = delete;

    void cancel()
    {
        m_closed = true;
        m_timer.cancel();
        m_pool.visit_all(
            [](auto& x)
            {
                x.first->cancel();
            }
        );
    }

    // TODO: error code if conn not found?
    void close_connection(std::shared_ptr<boost::redis::connection> conn)
    {
        m_pool.visit(
            conn, [&conn](auto& x)
            {
                std::cerr << std::format("POOL: close_connection: conn={}", fmt::ptr(&*conn))
                          << std::endl;
                x.second = false;
            }
        );

        // TODO: DEBUG.
        m_pool.cvisit_all(
            [](const auto& x)
            {
                std::cerr << std::format("fuck: {}: {}\n", fmt::ptr(&*x.first), x.second);
            }
        );
    }

    // TODO: error if closed?
    asio::awaitable <PoolConnection> acquire()
    {
        if (m_closed)
        {
            throw std::runtime_error("TODO: error codes etc (closed)");
        }

        std::shared_ptr<boost::redis::connection> conn = nullptr;

        // TODO: how to return early from here?
        m_pool.visit_all(
            [&conn](auto& x)
            {
                if (conn == nullptr && !x.second)
                {
                    x.second = true;
                    conn = x.first;
                }
            }
        );

        // TODO: DEBUG!!!
        m_pool.cvisit_all(
            [](const auto& x)
            {
                std::cerr << std::format("ACQUIRE: fuck: {}: {}\n", fmt::ptr(&*x.first), x.second);
            }
        );

        if (conn)
        {
            co_return PoolConnection{*this, conn};
        }

        // TODO: retrying or some shit?
        throw std::runtime_error("TODO: no conn!");
    }

private:
    void maintenance(const boost::system::error_code& error)
    {
        if (!error)
        {
            std::cerr << "MAINTENANCE TIME" << std::endl;

            // TODO: is this thread safe actually?
            m_pool.visit_all(
                [](auto& x)
                {
                    if (!x.second)
                    {
                        x.second = true; // TODO: is this stupid?

                        std::shared_ptr<boost::redis::connection> conn = x.first;
                        std::cerr << std::format("maintenance, conn={}", fmt::ptr(&*conn))
                                  << std::endl;

                        boost::redis::request req;
                        req.push("PING", "");
                        boost::system::error_code error{};
                        conn->async_exec(
                            req,
                            boost::redis::ignore,
                            asio::consign(asio::redirect_error(error), conn)
                        );

                        if (error)
                        {
                            // TODO: just ignore this error?
                            std::cerr << "ping error: " << error.message() << "\n";
                        }

                        x.second = false; // TODO: is this stupid?
                    }
                }
            );

            if (m_closed)
            {
                m_timer.cancel();
            }
            if (!m_closed)
            {
                m_timer.expires_from_now(m_timer_interval);
                m_timer.async_wait(
                    boost::bind(
                        &ConnectionPool::maintenance,
                        this,
                        boost::asio::placeholders::error
                    )
                );
            }
        }
    }

    // Map of pairs: [connection ptr, connection in use flag].
    boost::concurrent_flat_map<std::shared_ptr<boost::redis::connection>, bool> m_pool;
    boost::redis::config m_config;
    bool m_closed;
    asio::deadline_timer m_timer;
    boost::posix_time::time_duration m_timer_interval;
};

}

#endif // BUILD_COMMANDS_BOT_REDIS_POOL_HPP
