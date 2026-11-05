-- The batch assessment (decided 2026-11-04), for a database loaded before it. Safe to run twice.
--   docker compose exec -T db psql -U claimsense -d claimsense -v ON_ERROR_STOP=1 < this file

-- The batch service account's group.
ALTER TABLE claimsense.users DROP CONSTRAINT IF EXISTS users_user_group_check;
ALTER TABLE claimsense.users ADD CONSTRAINT users_user_group_check CHECK (user_group IN
    ('adjuster', 'senior-adjuster', 'fraud-investigator', 'total-loss-appraiser', 'batch-service'));
INSERT INTO claimsense.users (user_id, full_name, user_group, status, test_only)
VALUES ('claimsense-batch', 'ClaimSense batch assessment', 'batch-service', 'active', FALSE)
ON CONFLICT (user_id) DO NOTHING;

-- Change detection.
CREATE OR REPLACE FUNCTION claimsense.documents_fingerprint(p_claim_id TEXT) RETURNS TEXT
LANGUAGE sql STABLE AS $$
    SELECT md5(coalesce(string_agg(document_id || ':' || ocr_status || ':' || coalesce(md5(ocr_text), ''),
                                   '|' ORDER BY document_id), ''))
      FROM doc_store.documents
     WHERE claim_id = p_claim_id
$$;

ALTER TABLE claimsense.assessments ADD COLUMN IF NOT EXISTS trigger TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE claimsense.assessments DROP CONSTRAINT IF EXISTS assessments_trigger_check;
ALTER TABLE claimsense.assessments ADD CONSTRAINT assessments_trigger_check CHECK (trigger IN ('manual', 'batch'));
ALTER TABLE claimsense.assessments ADD COLUMN IF NOT EXISTS documents_fingerprint TEXT;

-- Assessments written before: take the documents as they are now, so only later changes count.
UPDATE claimsense.assessments
   SET documents_fingerprint = claimsense.documents_fingerprint(claim_id)
 WHERE documents_fingerprint IS NULL;
