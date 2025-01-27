-- The actual result of the task is stored by taskiq
-- in taskiq_result table, where result_id points to.
CREATE TABLE IF NOT EXISTS "build_task"
(
    task_id          TEXT        NOT NULL PRIMARY KEY,
    start_time       TIMESTAMPTZ NOT NULL,
    build_result_id  TEXT,
    git_hash         TEXT,
    hg_packages_hash TEXT,
    hg_maps_hash     TEXT,

    CONSTRAINT fk_result_id
        FOREIGN KEY (build_result_id)
            REFERENCES taskiq_result (task_id)

);

CREATE TABLE IF NOT EXISTS "workshop_upload_task"
(
    task_id                   TEXT        NOT NULL PRIMARY KEY,
    start_time                TIMESTAMPTZ NOT NULL,
    workshop_upload_result_id TEXT,
    git_hash                  TEXT,
    git_tag                   TEXT,
    hg_packages_hash          TEXT,
    hg_packages_tag           TEXT,
    hg_maps_hash              TEXT,
    hg_maps_tag               TEXT,

    CONSTRAINT fk_workshop_upload_result_id
        FOREIGN KEY (workshop_upload_result_id)
            REFERENCES taskiq_result (task_id)
);
