#ifndef BUILD_COMMANDS_BOT_REDIS_POOL_HPP
#define BUILD_COMMANDS_BOT_REDIS_POOL_HPP

#pragma once

#include <memory>

#include <boost/asio/detached.hpp>
#include <boost/asio/executor.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <boost/redis.hpp>
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
    // TODO: copy-constructors etc?

    Connection(
        ConnectionPool<ExecutorType>& pool,
        std::shared_ptr<boost::redis::connection> conn
    ) : conn(std::move(conn)), m_pool(pool)
    {
    }

    ~Connection()
    {
        close();
    }

    // TODO: should this be non-copyable?
    // Connection(const Connection&) = delete;

    Connection& operator=(const Connection&) = delete;

    // "Close" connection, i.e. return it to the pool.
    void close()
    {
        std::cerr << "CLOSING CONN!" << std::endl;
        m_pool.close_connection(conn);
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
        size_t pool_size = 4
    ) : m_config{std::move(config)}
    {
        for (auto i = 0; i < pool_size; ++i)
        {
            auto conn = std::make_shared<boost::redis::connection>(executor);
            std::cout << std::format("conn={}", fmt::ptr(&*conn)) << std::endl;
            // TODO: connection error callback?
            // conn->async_run(m_config, {}, asio::consign(asio::detached, conn));
            conn->async_run(
                m_config,
                boost::redis::logger{boost::redis::logger::level::debug},
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
    }

    // TODO: unique pointer?
    asio::awaitable <Connection<ExecutorType>> acquire()
    {
        std::shared_ptr<boost::redis::connection> conn = nullptr;

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

        if (conn)
        {
            co_return std::move(Connection<ExecutorType>{*this, conn});
        }

        // TODO: retrying or some shit?
        throw std::exception("TODO: no conn!");
    }

private:
    // TODO: vector of pairs: [in_use_flag, connection]
    boost::concurrent_flat_map<std::shared_ptr<boost::redis::connection>, bool> m_pool;
    boost::redis::config m_config;
};

}

#endif // BUILD_COMMANDS_BOT_REDIS_POOL_HPP
