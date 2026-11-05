-- ClaimSense — canonical schema (PostgreSQL 15+)
--
-- Four schemas, one per system:
--   claims_mgmt   client system: claims and the append-only claim notes ClaimSense writes
--   policy_admin  client system: policies and the policy manual (including one injected "bad chunk")
--   doc_store     client system: claim documents and their OCR text
--   claimsense    our system: users, the guarded clause index, drafts, retrieval, idempotency, audit
--
-- Tables are created in dependency order. Data comes from data/course_fixtures via seed/build_seed.py.
-- Expected outcomes and labels are deliberately NOT stored here.
-- Diagram: docs/ClaimSense-AI-Schema-ER-Diagram.pdf

CREATE SCHEMA IF NOT EXISTS claimsense;
CREATE SCHEMA IF NOT EXISTS policy_admin;
CREATE SCHEMA IF NOT EXISTS claims_mgmt;
CREATE SCHEMA IF NOT EXISTS doc_store;

-- ---------------------------------------------------------------------------
-- Users (from data/identity/users.json). Identity itself comes from Cognito tokens.
-- ---------------------------------------------------------------------------

CREATE TABLE claimsense.users (
    user_id     TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    user_group  TEXT CHECK (user_group IN
                  ('adjuster', 'senior-adjuster', 'fraud-investigator', 'total-loss-appraiser', 'batch-service')),
    status      TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
    test_only   BOOLEAN NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Policy administration
-- ---------------------------------------------------------------------------

CREATE TABLE policy_admin.policies (
    policy_id                    TEXT PRIMARY KEY CHECK (policy_id ~ '^POL-[A-Z]{3}-[0-9]{5}$'),
    holder_first                 TEXT NOT NULL,   -- PII: never returned by MCP tools
    holder_last                  TEXT NOT NULL,   -- PII: never returned by MCP tools
    vehicle_vin                  TEXT NOT NULL,   -- own copy (claims keep theirs)
    vehicle_year                 INT  NOT NULL,
    vehicle_make                 TEXT NOT NULL,
    vehicle_model                TEXT NOT NULL,
    vehicle_acv_usd              NUMERIC(12,2) NOT NULL,   -- agreed at inception, reference only
    coverage_type                TEXT NOT NULL CHECK (coverage_type IN ('Full Coverage', 'Liability Only')),
    collision_coverage           BOOLEAN NOT NULL,
    comprehensive_coverage       BOOLEAN NOT NULL,
    collision_deductible_usd     NUMERIC(12,2),   -- NULL when not covered ("N/A")
    comprehensive_deductible_usd NUMERIC(12,2),
    liability_limit              TEXT NOT NULL,
    medpay_limit_usd             NUMERIC(12,2) NOT NULL,
    policy_status                TEXT NOT NULL,   -- administrative only, never decides cover (CLS-PER-006)
    policy_start                 DATE NOT NULL,
    policy_end                   DATE NOT NULL,
    declarations_file            TEXT NOT NULL,
    CHECK (policy_end > policy_start)
);

-- The manual as the client system holds it, INCLUDING the injected bad chunk.
-- Agents never read this table; they search claimsense.clause_index.
CREATE TABLE policy_admin.policy_clauses (
    clause_id    TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    text         TEXT NOT NULL,
    source       TEXT NOT NULL,
    is_poisoned  BOOLEAN NOT NULL DEFAULT FALSE   -- test ground truth only; the guardrail must not read it
);

-- ---------------------------------------------------------------------------
-- Claims management
-- ---------------------------------------------------------------------------

CREATE TABLE claims_mgmt.claims (
    claim_id              TEXT PRIMARY KEY CHECK (claim_id ~ '^CLM-[0-9]{4}-[0-9]{4}$'),
    policy_id             TEXT NOT NULL REFERENCES policy_admin.policies (policy_id),
    vehicle_vin           TEXT NOT NULL,          -- own copy, compared with the policy by code
    vehicle_year          INT  NOT NULL,
    vehicle_make          TEXT NOT NULL,
    vehicle_model         TEXT NOT NULL,
    vehicle_acv_usd       NUMERIC(12,2) NOT NULL CHECK (vehicle_acv_usd > 0),  -- ACV at loss, used for payout
    incident_date         DATE NOT NULL,
    incident_type         TEXT NOT NULL,          -- mapped to a loss category in code
    incident_description  TEXT NOT NULL,          -- untrusted text
    damage_description    TEXT NOT NULL,          -- untrusted text
    repair_estimate_usd   NUMERIC(12,2) CHECK (repair_estimate_usd >= 0),
    injuries_reported     BOOLEAN NOT NULL,
    police_report_filed   BOOLEAN NOT NULL,
    assigned_adjuster     TEXT NOT NULL REFERENCES claimsense.users (user_id),
    prior_claims_12mo     INT NOT NULL CHECK (prior_claims_12mo >= 0),
    fraud_risk_score      NUMERIC(3,2) NOT NULL CHECK (fraud_risk_score BETWEEN 0 AND 1),
    claim_status          TEXT NOT NULL CHECK (claim_status IN
                            ('Approved', 'Pending Review', 'Under Investigation', 'Escalated')),
    created_at            TIMESTAMPTZ NOT NULL
);

-- ---------------------------------------------------------------------------
-- Document store
-- ---------------------------------------------------------------------------

CREATE TABLE doc_store.documents (
    document_id    TEXT PRIMARY KEY CHECK (document_id ~ '^DOC-[0-9]{5}$'),
    claim_id       TEXT NOT NULL REFERENCES claims_mgmt.claims (claim_id),
    document_type  TEXT NOT NULL CHECK (document_type IN ('FNOL_FORM', 'POLICE_REPORT', 'DAMAGE_PHOTOS',
                     'REPAIR_ESTIMATE', 'WITNESS_STATEMENT', 'MEDICAL_REPORT', 'RENTAL_RECEIPT')),
    description    TEXT NOT NULL,
    upload_date    DATE NOT NULL,
    page_count     INT NOT NULL CHECK (page_count >= 1),
    ocr_status     TEXT NOT NULL CHECK (ocr_status IN ('Completed', 'Pending', 'Failed')),
    uploaded_by    TEXT NOT NULL REFERENCES claimsense.users (user_id),
    file_path      TEXT NOT NULL,
    ocr_text       TEXT,                           -- untrusted text
    CHECK (ocr_status = 'Completed' OR ocr_text IS NULL)   -- CLS-DOC-009
);

-- ---------------------------------------------------------------------------
-- ClaimSense: the guarded clause corpus
-- The loader's guardrail puts every policy clause in exactly one of these two tables.
-- ---------------------------------------------------------------------------

CREATE TABLE claimsense.clause_index (
    clause_id  TEXT PRIMARY KEY REFERENCES policy_admin.policy_clauses (clause_id),
    title      TEXT NOT NULL,
    text       TEXT NOT NULL,
    search     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED,
    loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX clause_index_search ON claimsense.clause_index USING GIN (search);

CREATE TABLE claimsense.clause_quarantine (
    clause_id    TEXT PRIMARY KEY REFERENCES policy_admin.policy_clauses (clause_id),
    reason       TEXT NOT NULL,                    -- which guardrail pattern matched
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- ClaimSense: drafts, retrieval, the claim-note write-back, idempotency
-- ---------------------------------------------------------------------------

-- One full draft per pipeline run; never edited (a re-run adds a row).
-- A fingerprint of one claim's documents (id, OCR status, hash of the text). The batch assessment
-- compares it with the one stored on the claim's last assessment to see whether documents changed.
CREATE FUNCTION claimsense.documents_fingerprint(p_claim_id TEXT) RETURNS TEXT
LANGUAGE sql STABLE AS $$
    SELECT md5(coalesce(string_agg(document_id || ':' || ocr_status || ':' || coalesce(md5(ocr_text), ''),
                                   '|' ORDER BY document_id), ''))
      FROM doc_store.documents
     WHERE claim_id = p_claim_id
$$;

CREATE TABLE claimsense.assessments (
    assessment_id    BIGSERIAL PRIMARY KEY,
    run_id           UUID NOT NULL UNIQUE,
    claim_id         TEXT NOT NULL REFERENCES claims_mgmt.claims (claim_id),
    on_behalf_of     TEXT NOT NULL REFERENCES claimsense.users (user_id),
    outcome          TEXT NOT NULL CHECK (outcome IN ('APPROVE', 'FLAG', 'ROUTE', 'DENY')),
    -- agent_failure: an agent could not finish, so code wrote a DENY for an adjuster to assess
    decision_source  TEXT NOT NULL CHECK (decision_source IN ('model', 'deterministic_fallback', 'agent_failure')),
    code_facts       JSONB NOT NULL,               -- dates, money, ratios computed by code
    agent_outputs    JSONB NOT NULL,               -- typed output of each agent
    citations        TEXT[] NOT NULL DEFAULT '{}',
    models           JSONB NOT NULL,               -- model and prompt version per agent
    claim_status_at_run TEXT,                      -- the claim's status in the claims system when the run started
    trigger          TEXT NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual', 'batch')),
    documents_fingerprint TEXT,                    -- the claim's documents when the note was written (batch change detection)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The only write-back to a client system (open question 4): append-only.
CREATE TABLE claims_mgmt.claim_notes (
    note_id        BIGSERIAL PRIMARY KEY,
    claim_id       TEXT NOT NULL REFERENCES claims_mgmt.claims (claim_id),
    assessment_id  BIGINT NOT NULL REFERENCES claimsense.assessments (assessment_id),
    on_behalf_of   TEXT NOT NULL REFERENCES claimsense.users (user_id),
    outcome        TEXT NOT NULL CHECK (outcome IN ('APPROVE', 'FLAG', 'ROUTE', 'DENY')),
    summary        TEXT NOT NULL,                  -- built from structured fields, never copied document text
    cited_clauses  TEXT[] NOT NULL DEFAULT '{}',
    deny_reason    TEXT,                           -- e.g. 'no supporting clause found'
    status         TEXT NOT NULL DEFAULT 'draft_pending_confirmation',
    author         TEXT NOT NULL DEFAULT 'claimsense',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A note must cite clauses, unless it is a DENY that records why (questions 3 and 4).
    CHECK (cardinality(cited_clauses) > 0 OR (outcome = 'DENY' AND deny_reason IS NOT NULL))
);

-- An adjuster's review of a draft note: confirmed or rejected, once (decided 2026-11-04). The note
-- itself stays append-only; its status reads from here. A rejection, and any review of an
-- agent-failure DENY, carries a reason.
CREATE TABLE claims_mgmt.note_reviews (
    note_id      BIGINT PRIMARY KEY REFERENCES claims_mgmt.claim_notes (note_id),
    decision     TEXT NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
    reviewed_by  TEXT NOT NULL REFERENCES claimsense.users (user_id),
    reason       TEXT,
    reviewed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE claimsense.retrieval_log (
    retrieval_id  BIGSERIAL PRIMARY KEY,
    run_id        UUID NOT NULL,                   -- the assessment run (written before the assessment exists)
    agent         TEXT NOT NULL,
    query         TEXT NOT NULL,
    clause_ids    TEXT[] NOT NULL,                 -- what came back; citations must be a subset
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX retrieval_log_run ON claimsense.retrieval_log (run_id);

-- Retries after a timeout reuse the key: same payload returns the stored note, a different payload gets 409.
CREATE TABLE claimsense.idempotency_keys (
    user_id       TEXT NOT NULL,
    idem_key      TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    note_id       BIGINT REFERENCES claims_mgmt.claim_notes (note_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, idem_key)
);

-- Requests per user per minute, for the API's rate limit (api/src/claimsense_api/ratelimit.py).
CREATE TABLE claimsense.rate_limit (
    user_id        TEXT NOT NULL,
    window_start   TIMESTAMPTZ NOT NULL,            -- the minute being counted
    request_count  INTEGER NOT NULL,
    PRIMARY KEY (user_id, window_start)
);

-- ---------------------------------------------------------------------------
-- Audit log — every request and tool call, allowed or denied (reused from the sample, plus OBO columns)
-- ---------------------------------------------------------------------------

CREATE TABLE claimsense.audit_log (
    audit_id       BIGSERIAL PRIMARY KEY,
    user_id        TEXT,                           -- caller from the verified token (NULL if no valid token)
    user_group     TEXT,
    on_behalf_of   TEXT,                           -- the human an agent acts for
    actor          TEXT NOT NULL,                  -- 'human' or the agent name
    action         TEXT NOT NULL,                  -- get_claim | list_documents | search_clauses | write_note | confirm ...
    resource_type  TEXT,
    resource_id    TEXT,
    decision       TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'error')),
    reason         TEXT,                           -- full reason here only, never sent to the caller
    run_id         UUID,
    detail         JSONB,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_ts ON claimsense.audit_log (ts);
CREATE INDEX audit_log_user ON claimsense.audit_log (user_id);

-- ---------------------------------------------------------------------------
-- Console work queue (pattern of the sample's dispute_queue view)
-- ---------------------------------------------------------------------------

CREATE VIEW claimsense.claim_queue AS
SELECT
    c.claim_id,
    c.incident_date,
    c.incident_type,
    c.claim_status,
    c.repair_estimate_usd,
    c.vehicle_acv_usd,
    c.fraud_risk_score,
    c.assigned_adjuster,
    u.full_name   AS adjuster_name,
    p.coverage_type,
    p.policy_end
FROM claims_mgmt.claims c
JOIN policy_admin.policies p ON p.policy_id = c.policy_id
JOIN claimsense.users u      ON u.user_id = c.assigned_adjuster;
