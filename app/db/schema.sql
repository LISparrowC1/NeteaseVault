-- NeteaseVault schema. One row per logical thing; history lives in process_log.
--
-- `track` keeps the cloud axis (present/playable) and the local axis (local_state)
-- apart on purpose: a song disappearing from the liked list must not erase what the
-- downloader already achieved for it.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS playlist (
    id           INTEGER PRIMARY KEY,
    name         TEXT,
    last_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS track (
    song_id           INTEGER PRIMARY KEY,
    order_index       INTEGER NOT NULL,
    add_time          INTEGER,           -- cloud "added to playlist" time, ms
    title             TEXT,
    artist            TEXT,
    album             TEXT,
    duration_ms       INTEGER,
    cloud_max_quality TEXT,              -- maxBrLevel as reported by the cloud
    cover_url         TEXT,              -- album art URL from the cloud
    cloud_playable    INTEGER NOT NULL DEFAULT 1,
    cloud_present     INTEGER NOT NULL DEFAULT 1,
    local_state       TEXT NOT NULL DEFAULT 'none',
    local_rel_path    TEXT,
    local_format      TEXT,
    local_quality     TEXT,
    local_duration_ms INTEGER,
    first_seen_at     TEXT,
    last_seen_at      TEXT,
    removed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_track_order ON track(order_index);

CREATE TABLE IF NOT EXISTS sync_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    total       INTEGER,
    added       INTEGER,
    removed     INTEGER,
    invalid     INTEGER
);

-- One search candidate snapshot per attempt; keeps the raw payload for tracing.
CREATE TABLE IF NOT EXISTS candidate (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id     INTEGER NOT NULL,
    source      TEXT NOT NULL,
    channel     TEXT,                    -- musicdl / source / official
    script      TEXT,
    raw_json    TEXT,
    title       TEXT,
    artist      TEXT,
    album       TEXT,
    duration_ms INTEGER,
    qualities   TEXT,
    size_bytes  INTEGER,
    match_json  TEXT,
    passed      INTEGER,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidate_song ON candidate(song_id);

CREATE TABLE IF NOT EXISTS download_job (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id     INTEGER NOT NULL,
    candidate_id INTEGER,
    channel     TEXT,
    quality     TEXT,
    url         TEXT,
    status      TEXT,
    error       TEXT,
    bytes       INTEGER,
    started_at  TEXT,
    finished_at TEXT
);

-- Append-only record of what happened to a track, for problem tracing.
CREATE TABLE IF NOT EXISTS process_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id     INTEGER,
    job_id      INTEGER,
    stage       TEXT,
    detail_json TEXT,
    elapsed_ms  INTEGER,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_log_song ON process_log(song_id);

CREATE TABLE IF NOT EXISTS approval (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id        INTEGER NOT NULL,
    reason         TEXT,
    candidates_json TEXT,
    decision       TEXT,                 -- pending / accepted / rejected
    decided_at     TEXT,
    note           TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS source_script (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT,
    version       TEXT,
    file_path     TEXT,
    enabled       INTEGER DEFAULT 1,
    priority      INTEGER DEFAULT 0,
    sources_json  TEXT,                  -- supported sources and quality tiers
    last_check_at TEXT,
    last_check_ok INTEGER,
    last_latency_ms INTEGER,
    note          TEXT
);
