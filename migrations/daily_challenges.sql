-- Drop existing table if it exists
DROP TABLE IF EXISTS daily_challenges;

-- Create daily_challenges table with proper foreign key constraints
CREATE TABLE daily_challenges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    map_md5 CHAR(32) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    mode TINYINT NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (map_md5) 
        REFERENCES maps (md5)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_active_time (active, start_time, end_time),
    INDEX idx_map_md5 (map_md5)
);