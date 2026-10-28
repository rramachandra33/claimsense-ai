"""Keep personal details out of the claim note.

The note is the one thing ClaimSense writes into the client's claims system, so code (not the
model's instructions) makes sure it holds no street addresses, phone numbers or emails. Agent
outputs are left as they are: they stay in ClaimSense's own assessment record, which only people
allowed to read the claim's documents can see.

Names cannot be found reliably by a pattern, so for names we still rely on the agents' instructions.
"""
import re

# Each pattern, and what replaces a match.
PATTERNS = [
    # emails: someone@example.com
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    # US phone numbers: (713) 555-4024, 713-555-4024, 713.555.4024, 713 555 4024
    (re.compile(r"(\(\d{3}\)\s*|\b\d{3}[-.\s])\d{3}[-.\s]\d{4}\b"), "[phone]"),
    # street addresses: a house number, up to four capitalised words, a street type, and an
    # optional ", City" and ", ST 12345" after it, e.g. "3032 Washington Ave, Houston, TX 77044"
    (re.compile(r"\b\d{1,6}\s+(?:[A-Z][A-Za-z]*\s+){1,4}"
                r"(?:Avenue|Ave|Street|St|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct"
                r"|Place|Pl|Parkway|Pkwy|Highway|Hwy)\b"
                r"(?:,\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)?"
                r"(?:,\s*[A-Z]{2}\s*\d{5})?"), "[address]"),
]


def redact(text):
    """Return (text with personal details replaced, how many were replaced)."""
    if not text:
        return text, 0
    count = 0
    for pattern, replacement in PATTERNS:
        text, found = pattern.subn(replacement, text)
        count += found
    return text, count
