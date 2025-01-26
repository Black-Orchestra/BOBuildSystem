-- The actual result of the task is stored by taskiq
-- in taskiq_result table, where result_id points to.
CREATE TABLE IF NOT EXISTS "task"
(
    task_id    TEXT        NOT NULL PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL,
    result_id  TEXT,

    CONSTRAINT fk_result_id
        FOREIGN KEY (result_id)
            REFERENCES taskiq_result (task_id)
);
