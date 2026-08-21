"""Shared test setup.

The fast test suite talks to the external service (external_service/) over
HTTP, but through an in-process ASGI transport -- no real port, no real
network socket, while still exercising the actual request/response/JSON
cycle rather than mocking the integration away. The external service's order
data and the mocked Salesforce Case table (app/salesforce.py) both reset
between tests, since operations like initiate_return / escalate_to_human
mutate them.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import salesforce, store
from external_service import data_store as eds
from external_service.main import app as external_app


@pytest.fixture(autouse=True)
def in_process_external_service():
    eds.reset()
    # TestClient IS an httpx.Client (Starlette subclasses it), just backed by
    # an in-process ASGI transport instead of a real socket -- so it's a
    # drop-in for store.py's real httpx.Client with zero network involved.
    store.set_client(TestClient(external_app, base_url="http://testserver"))
    yield
    eds.reset()


@pytest.fixture(autouse=True)
def isolate_salesforce_cases():
    salesforce.reset()
    yield
    salesforce.reset()
