"""Shared test setup. initiate_return mutates the in-memory mock store (marks
items returned, appends tickets/returns) -- without this, one test's mutation
would leak into every test that runs after it in the same pytest process.
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store


@pytest.fixture(autouse=True)
def isolate_store():
    snapshot = (
        copy.deepcopy(store._ORDERS),
        copy.deepcopy(store._RETURNS),
        copy.deepcopy(store._TICKETS),
        store._next_return_id,
        store._next_ticket_id,
    )
    yield
    store._ORDERS, store._RETURNS, store._TICKETS, store._next_return_id, store._next_ticket_id = snapshot
