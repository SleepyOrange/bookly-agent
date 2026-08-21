"""Guardrails layer tests -- identity verification and PII masking in isolation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import guardrails


def test_verify_identity_success():
    order, err = guardrails.verify_identity("BK-10234", "alice@example.com")
    assert err is None
    assert order["order_id"] == "BK-10234"


def test_verify_identity_wrong_email():
    order, err = guardrails.verify_identity("BK-10234", "not-alice@example.com")
    assert order is None
    assert err["error"] == "identity_mismatch"


def test_verify_identity_unknown_order():
    order, err = guardrails.verify_identity("BK-99999", "alice@example.com")
    assert order is None
    assert err["error"] == "not_found"


def test_mask_email():
    assert guardrails.mask_email("alice@example.com") == "a***e@example.com"
