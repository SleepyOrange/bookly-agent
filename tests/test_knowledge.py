"""Knowledge layer tests -- policy search grounding."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge


def test_search_policy_relevant_query():
    result = knowledge.search_policy("how many days do I have to return something")
    assert "matches" in result
    assert any("30 days" in m["text"] for m in result["matches"])


def test_search_policy_no_match():
    result = knowledge.search_policy("xyzzy quux plugh nonsense query")
    assert result["error"] == "no_match"
