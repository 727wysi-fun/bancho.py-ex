-- Daily challenges optimization indexes

-- Index for fetching active challenges
CREATE INDEX idx_daily_challenges_active ON daily_challenges(active, start_time, end_time);

-- Index for querying by map_md5
CREATE INDEX idx_daily_challenges_map_md5 ON daily_challenges(map_md5);

-- Index for checking recent maps to avoid repetition
CREATE INDEX idx_daily_challenges_created_at ON daily_challenges(created_at);
