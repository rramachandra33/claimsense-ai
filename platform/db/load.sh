#!/usr/bin/env bash
# One-command local load: schema + deterministic seed CSVs → local Postgres.
# Usage: ./load.sh [demo|full]   (default: demo)
set -euo pipefail
cd "$(dirname "$0")"

SCALE="${1:-demo}"
DB_URL="${CLAIMSENSE_DB_URL:-postgresql://claimsense:claimsense@localhost:5432/claimsense}"

echo "==> generating $SCALE seed (deterministic)…"
( cd seed && uv run --with faker python generate.py --scale "$SCALE" --out ./data )

echo "==> waiting for Postgres at ${DB_URL}…"
until docker compose exec -T claimsense-db pg_isready -U claimsense >/dev/null 2>&1; do sleep 1; done

echo "==> applying schema (clean reset)…"
docker compose exec -T claimsense-db psql -U claimsense -d claimsense -q -c "DROP SCHEMA IF EXISTS claimsense CASCADE;"
docker compose exec -T claimsense-db psql -U claimsense -d claimsense -q -v ON_ERROR_STOP=1 < schema.sql

echo "==> loading CSVs (load order respects FKs)…"
# analysts before disputes (FK); customers/accounts/merchants/transactions before disputes.
# Explicit column list from each CSV header so DEFAULTed columns (e.g. created_at) are skipped.
for t in customers accounts merchants transactions analysts disputes dispute_evidence tickets policy_chunks; do
  cols=$(head -1 "seed/data/$t.csv")
  rows=$(($(wc -l < "seed/data/$t.csv") - 1))
  echo "    $t ($rows rows)…"
  docker compose exec -T claimsense-db \
    psql -U claimsense -d claimsense -v ON_ERROR_STOP=1 \
    -c "\copy claimsense.$t ($cols) FROM STDIN WITH (FORMAT csv, HEADER true)" < "seed/data/$t.csv"
done

echo "==> sanity:"
docker compose exec -T claimsense-db psql -U claimsense -d claimsense -c \
  "SELECT (SELECT count(*) FROM claimsense.transactions) AS txns,
          (SELECT count(*) FROM claimsense.disputes WHERE sla_breached) AS breaches,
          (SELECT count(*) FROM claimsense.policy_chunks WHERE is_poisoned) AS poisoned;"
echo "==> done. Connect: $DB_URL"
