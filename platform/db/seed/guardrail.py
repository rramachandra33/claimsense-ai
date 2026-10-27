"""Load-time guardrail for policy clauses (open question 3).

A clause is quarantined when its text looks like an instruction aimed at the AI instead of policy
wording. The check reads only the clause text; it never looks at the is_poisoned test flag.
"""
import re

# Each entry: (pattern, reason). Patterns are case-insensitive.
INJECTION_PATTERNS = [
    (r"ignore (all |any )?(previous|prior|above) (instructions|rules|constraints)", "asks to ignore instructions"),
    (r"system instruction", "claims to be a system instruction"),
    (r"\bassistant\b", "addresses the AI directly"),
    (r"\bthe (ai|model)\b", "addresses the AI directly"),
    (r"overrides? (the )?(policy|manual)", "claims to override the manual"),
    (r"do not cite", "tells the model not to cite"),
    (r"approve (every|all) claims?", "orders blanket approval"),
]


def find_injection(text):
    """Return the reason for the first matching pattern, or None if the text looks clean."""
    for pattern, reason in INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return reason
    return None
