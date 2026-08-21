"""Knowledge layer tests -- policy lookup grounding."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge


def test_get_policy_known_topic():
    result = knowledge.get_policy("returns")
    assert "30 days" in result["policy"]


def test_get_policy_unknown_topic_lists_alternatives():
    result = knowledge.get_policy("shipping_but_typo")
    # enum-constrained by the tool schema in practice; defensive check here
    assert result["error"] == "unknown_topic"
    assert "shipping" in result["available_topics"]
