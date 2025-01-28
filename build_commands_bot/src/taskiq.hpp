// This file implements a simple C++ interface to publish
// taskiq messages to Redis similarly to how PubSubBroker
// does it in taskiq_redis Python package.

#ifndef TASKIQ_HPP
#define TASKIQ_HPP

#pragma once

#include <string>
#include <vector>
// #include <flat_map>

namespace taskiq
{

struct BrokerMessage
{
    std::string task_id;
    std::string task_name;
    std::vector<std::uint8_t> message;
    // TODO: labels
};

} // taskiq

#endif // TASKIQ_HPP
