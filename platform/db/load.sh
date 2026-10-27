#!/usr/bin/env bash
# One-command local load: schema + course-fixture seed CSVs -> local Postgres.
# Usage: ./load.sh        (run `docker compose up -d` first; `make up` does both)
set -euo pipefail
cd "$(dirname "$0")"

DB_URL="${CLAIMSENSE_DB_URL:-postgresql://claimsense:claimsense@localhost:5433/claimsense}"
PSQL=(docker compose exec -T claimsense-db psql -U claimsense -d claimsense -v ON_ERROR_STOP=1)

echo "==> building seed CSVs (guardrail runs here)…"
python3 seed/build_seed.py

echo "==> waiting for Postgres at ${DB_URL}…"
until docker compose exec -T claimsense-db pg_isready -U claimsense >/dev/null 2>&1; do sleep 1; done

echo "==> applying schema (clean reset)…"
"${PSQL[@]}" -q -c "DROP SCHEMA IF EXISTS claimsense, policy_admin, claims_mgmt, doc_store CASCADE;"
"${PSQL[@]}" -q < schema.sql

echo "==> loading CSVs (order respects foreign keys)…"
# schema.table pairs; each CSV's header line gives its column list
for target in claimsense.users policy_admin.policies policy_admin.policy_clauses claims_mgmt.claims \
              doc_store.documents claimsense.clause_index claimsense.clause_quarantine; do
  table="${target#*.}"
  cols=$(head -1 "seed/data/$table.csv")
  echo "    $target"
  "${PSQL[@]}" -q -c "\copy $target ($cols) FROM STDIN WITH (FORMAT csv, HEADER true)" < "seed/data/$table.csv"
done

echo "==> sanity:"
"${PSQL[@]}" -c "
SELECT (SELECT count(*) FROM claims_mgmt.claims)              AS claims,
       (SELECT count(*) FROM policy_admin.policies)           AS policies,
       (SELECT count(*) FROM doc_store.documents)             AS documents,
       (SELECT count(*) FROM claimsense.users)                AS users,
       (SELECT count(*) FROM claimsense.clause_index)         AS clauses_indexed,
       (SELECT count(*) FROM claimsense.clause_quarantine)    AS clauses_quarantined,
       (SELECT count(*) FROM claimsense.clause_index i
          JOIN policy_admin.policy_clauses c USING (clause_id)
         WHERE c.is_poisoned)                                 AS poisoned_in_index;"
echo "==> done. Connect: $DB_URL"
