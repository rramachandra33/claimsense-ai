-- Brings a database loaded before 2026-11-04 up to date without reloading it (EC2):
--   docker compose exec -T db psql -U claimsense -d claimsense -v ON_ERROR_STOP=1 < this file
-- Safe to run twice. A fresh load (schema.sql) already has both.

ALTER TABLE claimsense.assessments ADD COLUMN IF NOT EXISTS claim_status_at_run TEXT;

CREATE TABLE IF NOT EXISTS claims_mgmt.note_reviews (
    note_id      BIGINT PRIMARY KEY REFERENCES claims_mgmt.claim_notes (note_id),
    decision     TEXT NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
    reviewed_by  TEXT NOT NULL REFERENCES claimsense.users (user_id),
    reason       TEXT,
    reviewed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
