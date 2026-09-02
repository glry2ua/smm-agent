-- The `keywords` table has always been a list of content topics the weekly
-- job picks from; rename it so the table, the code, and the UI all say
-- "topics". Row data is untouched.

ALTER TABLE keywords RENAME TO topics;

DROP INDEX IF EXISTS idx_keywords_used_at;
CREATE INDEX IF NOT EXISTS idx_topics_used_at ON topics(used_at);