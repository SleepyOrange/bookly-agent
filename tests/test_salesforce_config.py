"""Safety-critical config tests for the real/mock Salesforce switch. These
matter more than most tests in this repo: a regression here could mean the
agent starts creating real Cases in a production org by accident. Always
run, no credentials needed.

The default-mode checks use a subprocess with a clean environment rather
than monkeypatching the already-imported module -- monkeypatch can prove
"the attribute can be set to X," but only a fresh interpreter can prove
"this is genuinely what happens with nothing else touching it first."
"""
import os
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import salesforce

REPO_ROOT = Path(__file__).resolve().parent.parent
_CHECK_MODE_SCRIPT = "import sys; sys.path.insert(0, '.'); from app import salesforce; print(salesforce.MODE)"


def test_default_mode_is_mock_in_a_clean_environment():
    env = {k: v for k, v in os.environ.items() if k != "BOOKLY_SALESFORCE_MODE"}
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_MODE_SCRIPT],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.stdout.strip() == "mock", f"stderr: {result.stderr}"


def test_mode_becomes_real_only_when_explicitly_set():
    env = {**os.environ, "BOOKLY_SALESFORCE_MODE": "real"}
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_MODE_SCRIPT],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.stdout.strip() == "real", f"stderr: {result.stderr}"


def test_mode_stays_mock_even_with_credentials_present(monkeypatch):
    """Presence of credentials alone must never be enough to go live --
    BOOKLY_SALESFORCE_MODE has to be set to "real" explicitly."""
    env = {
        **{k: v for k, v in os.environ.items() if k != "BOOKLY_SALESFORCE_MODE"},
        "SALESFORCE_CLIENT_ID": "fake",
        "SALESFORCE_CLIENT_SECRET": "fake",
        "SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
    }
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_MODE_SCRIPT],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.stdout.strip() == "mock", f"stderr: {result.stderr}"


def test_mock_mode_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(salesforce, "MODE", "mock")

    def boom(*args, **kwargs):
        raise AssertionError("mock mode must never make an HTTP call")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "get", boom)

    result = salesforce.create_case("A test subject", "A test description")
    assert result["Id"].startswith("500")
