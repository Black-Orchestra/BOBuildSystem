// This file implements a simple C++ interface to publish
// taskiq messages to Redis similarly to how PubSubBroker
// does it in taskiq_redis Python package.

#ifndef TASKIQ_HPP
#define TASKIQ_HPP

#pragma once

#include <map> // TODO: use different map implementation?
#include <string>
#include <vector>

#include <glaze/glaze.hpp>

namespace taskiq
{

constexpr auto bo_build_lock_name = "bobuild.tasks_bo._UNIQUE_TASK__LOCK";
constexpr auto bo_upload_to_workshop_task_name = "bobuild.tasks_bo.upload_to_workshop";
constexpr auto bo_workshop_upload_task_label = "workshop_upload_task";
constexpr auto bo_task_label_key = "task_label";

// Publish message JSON bytes to Redis to send the task to worker(s).
// {
//     "task_name": "my_project.module1.task",
//     "args": [1, 2, 3],
//     "kwargs": {"a": 1, "b": 2, "c": 3},
//     "labels": {
//         "label1": "value1",
//         "label2": "value2"
//     }
// }
struct Message
{
    std::string task_name{};
    std::vector<std::any> args;
    std::map<std::string, std::any> kwargs{};
    std::map<std::string, std::any> labels{};
};
static_assert(glz::detail::reflectable<Message>);

inline Message make_bo_sws_upload_msg()
{
    Message msg{};
    msg.task_name = bo_upload_to_workshop_task_name;
    msg.labels[bo_task_label_key] = bo_workshop_upload_task_label;
    return msg;
}

} // taskiq

#endif // TASKIQ_HPP
