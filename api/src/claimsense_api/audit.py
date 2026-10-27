"""Audit log writer. (Ported from the sample's audit.ts, plus the on-behalf-of columns.)

Every call writes one row, allowed or denied. Writing the audit row must never break the request,
so a failure is printed and the request carries on.
"""
import json

from .db import execute


def log_audit(action, decision, user=None, resource_type=None, resource_id=None, reason=None,
              actor="human", on_behalf_of=None, run_id=None, detail=None):
    user_id = user["user_id"] if user else None
    user_group = user["user_group"] if user else None
    try:
        execute(
            """INSERT INTO claimsense.audit_log
                 (user_id, user_group, on_behalf_of, actor, action, resource_type, resource_id,
                  decision, reason, run_id, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, user_group, on_behalf_of, actor, action, resource_type, resource_id,
             decision, reason, run_id, json.dumps(detail) if detail is not None else None),
        )
    except Exception as e:
        print(f"[audit] failed to write audit row: {e}")
