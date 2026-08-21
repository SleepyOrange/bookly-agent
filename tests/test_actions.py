"""Actions layer tests -- order lookup, return eligibility/initiation,
password reset, and that the identity guardrail actually blocks bad requests
at the action boundary (not just in guardrails.py in isolation)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import actions


def test_lookup_order_success():
    result = actions.lookup_order("BK-10234", "alice@example.com")
    assert result["status"] == "Delivered"
    assert result["order_id"] == "BK-10234"


def test_lookup_order_wrong_email_blocks_details():
    result = actions.lookup_order("BK-10234", "not-alice@example.com")
    assert result["error"] == "identity_mismatch"
    assert "status" not in result


def test_lookup_order_not_found():
    result = actions.lookup_order("BK-99999", "alice@example.com")
    assert result["error"] == "not_found"


def test_return_eligibility_within_window():
    # BK-10234 delivered 2026-08-09, well within the 30-day window
    result = actions.check_return_eligibility("BK-10234", "alice@example.com")
    assert result["eligible"] is True


def test_return_eligibility_past_window():
    # BK-11020 delivered 2026-07-06, more than 30 days ago
    result = actions.check_return_eligibility("BK-11020", "bob@example.com")
    assert result["eligible"] is False


def test_return_eligibility_not_delivered():
    result = actions.check_return_eligibility("BK-11500", "bob@example.com")
    assert result["eligible"] is False


def test_initiate_return_success_and_refund_amount():
    result = actions.initiate_return(
        "BK-10234", "alice@example.com", "Project Hail Mary", "Changed my mind"
    )
    assert result["status"] == "Return initiated"
    assert result["refund_amount"] == 14.99
    assert result["return_id"].startswith("RT-")


def test_initiate_return_unknown_item():
    result = actions.initiate_return(
        "BK-10234", "alice@example.com", "A Book That Does Not Exist", "N/A"
    )
    assert result["error"] == "not_eligible"


def test_send_password_reset_masks_email():
    result = actions.send_password_reset("alice@example.com")
    assert "a***e@example.com" in result["message"]


def test_ebook_not_eligible_for_return():
    result = actions.check_return_eligibility("BK-12010", "alice@example.com", "Digital Fortress")
    assert result["eligible"] is False
    assert "final sale" in result["reason"]


def test_initiate_return_rejects_ebook():
    result = actions.initiate_return("BK-12010", "alice@example.com", "Digital Fortress", "Didn't like it")
    assert result["error"] == "not_eligible"


def test_already_returned_item_not_eligible():
    result = actions.check_return_eligibility("BK-12200", "alice@example.com", "Educated")
    assert result["eligible"] is False
    assert "already been returned" in result["reason"]


def test_cancelled_order_not_eligible():
    result = actions.check_return_eligibility("BK-12100", "bob@example.com")
    assert result["eligible"] is False
    assert "cancelled" in result["reason"].lower()


def test_initiate_return_marks_item_returned_for_future_checks():
    first = actions.initiate_return("BK-10234", "alice@example.com", "Project Hail Mary", "Changed my mind")
    assert first["status"] == "Return initiated"
    second = actions.check_return_eligibility("BK-10234", "alice@example.com", "Project Hail Mary")
    assert second["eligible"] is False
    assert "already been returned" in second["reason"]
