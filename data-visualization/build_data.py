#!/usr/bin/env python3
"""Bundle the eval cases and the records they reference into data.json for claim-explorer.html.

    python3 data-visualization/build_data.py

Run it after re-running scripts/generate_synthetic_data.py.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
OUT = Path(__file__).resolve().parent / "data.json"


def load(name):
    return json.loads((DATA / name).read_text())


cases = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text().splitlines() if line]
claims = {c["claim_id"]: c for c in load("claims.json")}
policies = {p["policy_id"]: p for p in load("policies.json")}
docs = {}
for d in load("documents.json"):
    docs.setdefault(d["claim_id"], []).append(d)

needed = sorted({c["claim_id"] for c in cases if c["claim_id"]})
bundle = {
    "cases": cases,
    "claims": {k: claims[k] for k in needed},
    "policies": {claims[k]["policy_id"]: policies[claims[k]["policy_id"]] for k in needed},
    "docs": {k: docs.get(k, []) for k in needed},
    "history": load("claim_history.json"),
    "clauses": load("policy_clauses.json"),
    "users": load("users.json"),
}
OUT.write_text(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False))
print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(cases)} cases)")
