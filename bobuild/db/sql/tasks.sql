-- The actual result of the task is stored by taskiq
-- in taskiq_result table, where result_id points to.
CREATE TABLE IF NOT EXISTS "task"
(
    id                 TEXT        NOT NULL PRIMARY KEY,
    start_time         TIMESTAMPTZ NOT NULL,
    result_id          TEXT,
    discord_message_id BIGINT
);
