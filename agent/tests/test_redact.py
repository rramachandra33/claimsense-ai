"""Personal details are removed from the note. No database or API needed."""
import pytest

from claimsense_agent.redact import redact


@pytest.mark.parametrize("text, expected", [
    ("Loss at 3032 Washington Ave, Houston, TX 77044 per the FNOL.", "Loss at [address] per the FNOL."),
    ("Police report says 4291 Montrose Blvd, Houston, TX 77081.", "Police report says [address]."),
    ("Shop at 18 North Main Street.", "Shop at [address]."),
    ("Call (713) 555-4024 or 713-555-4024.", "Call [phone] or [phone]."),
    ("Email j.morrison@example.com today.", "Email [email] today."),
])
def test_personal_details_are_replaced(text, expected):
    assert redact(text)[0] == expected


def test_claim_facts_are_left_alone():
    text = ("Draft APPROVE, pending adjuster confirmation. 2021 Toyota Camry, loss 2024-02-14 on "
            "CLM-2024-1800 (DOC-00072). Repair estimate $3,200, deductible $500, net payable $2,700, "
            "limit 300000/100000, VIN 4T1BF1FK5MU500123, cites CLS-COLL-001.")
    assert redact(text) == (text, 0)


def test_count_and_empty_values():
    assert redact("3032 Washington Ave and (713) 555-4024")[1] == 2
    assert redact(None) == (None, 0)
    assert redact("") == ("", 0)
