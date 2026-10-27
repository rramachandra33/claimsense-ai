#!/usr/bin/env python3
"""Build the JSON the frontend imports from data/synthetic/.

    python3 frontend/scripts/build_frontend_data.py

Writes frontend/src/data/{claims_open,users,access,demo_tokens}.json. Deterministic:
the demo tokens use fixed timestamps and a fixed DEMO secret, so re-running gives
identical files. Run it after re-running scripts/generate_synthetic_data.py.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic"
OUT = Path(__file__).resolve().parents[1] / "src" / "data"

# Demo only. The real backend keeps its signing key server side and never ships it.
DEMO_SECRET = "claimsense-demo-secret-not-for-production"
ISSUED_AT = 1767225600  # 2026-01-01T00:00:00Z
VALID_UNTIL = 1893456000  # 2030-01-01T00:00:00Z
EXPIRED_AT = 1735689600  # 2025-01-01T00:00:00Z


def load(name):
    return json.loads((DATA / name).read_text())


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(payload):
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(DEMO_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{b64url(sig)}"


def claims_for(user, exp=VALID_UNTIL):
    return {"sub": user["user_id"], "role": user["role"], "regions": user["regions"], "iat": ISSUED_AT, "exp": exp}


def write(name, obj):
    path = OUT / name
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(ROOT)}")


users_file = load("users.json")
users = {u["user_id"]: u for u in users_file["users"]}

claims_open = sorted(
    (
        {
            "claim_id": c["claim_id"],
            "region": c["region"],
            "loss_type": c["loss_type"],
            "loss_at": c["loss_at"],
            "vehicle": c["vehicle_description"],
            "assigned_adjuster": c["assigned_adjuster"],
            "adjuster_name": users[c["assigned_adjuster"]]["name"],
        }
        for c in load("claims.json")
        if c["status"] == "open"
    ),
    key=lambda c: c["claim_id"],
)

user_rows = [
    {k: u[k] for k in ("user_id", "name", "role", "regions", "status", "authority_limit")}
    for u in users_file["users"]
]

tokens = []
for uid, label in [
    ("u-adj-n1", "Adjuster NORTH"),
    ("u-adj-w1", "Adjuster WEST"),
    ("u-adj-n3", "Suspended adjuster"),
    ("u-sup-1", "Supervisor"),
    ("u-aud-1", "Auditor"),
    ("svc-pipeline", "Service account"),
]:
    tokens.append({"label": label, "user_id": uid, "token": sign(claims_for(users[uid]))})

tokens.append({"label": "Expired token", "user_id": "u-adj-n1", "token": sign(claims_for(users["u-adj-n1"], EXPIRED_AT))})

# Tampered: a WEST adjuster's token whose payload was edited to add NORTH, keeping the old signature.
west = sign(claims_for(users["u-adj-w1"]))
forged = dict(claims_for(users["u-adj-w1"]), regions=["WEST", "NORTH"])
header, _, sig = west.split(".")
tokens.append({
    "label": "Tampered token",
    "user_id": "u-adj-w1",
    "token": f"{header}.{b64url(json.dumps(forged, separators=(',', ':')).encode())}.{sig}",
})

OUT.mkdir(parents=True, exist_ok=True)
write("claims_open.json", claims_open)
write("users.json", user_rows)
write("access.json", {"access_rule": users_file["access_rule"], "demo_secret": DEMO_SECRET})
write("demo_tokens.json", tokens)
print(f"{len(claims_open)} open claims, {len(user_rows)} users, {len(tokens)} demo tokens")
