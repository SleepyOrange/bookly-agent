"""Tests for the AWS FAQ Lambda (aws/faq_function/app.py). The only AWS call
this handler makes is bedrock-agent-runtime.retrieve; a small fake client
returning a canned response (matching the real shape observed against the
live Knowledge Base during development) is enough to exercise the handler's
own logic without needing Bedrock, S3 Vectors, or network access.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("KNOWLEDGE_BASE_ID", "test-kb-id")
from aws.faq_function import app as lambda_app  # noqa: E402


class FakeBedrockClient:
    def __init__(self, results):
        self._results = results
        self.last_call = None

    def retrieve(self, **kwargs):
        self.last_call = kwargs
        return {"retrievalResults": self._results}


SAMPLE_RESULTS = [
    {
        "content": {"text": "Standard shipping takes 5-7 business days and costs £4.99 (free on orders over £35)."},
        "score": 0.61,
        "location": {"s3Location": {"uri": "s3://bookly-faq-docs/policies/shipping.txt"}},
    },
    {
        "content": {"text": "Once we receive and inspect a returned item, refunds are issued within 5-7 business days."},
        "score": 0.55,
        "location": {"s3Location": {"uri": "s3://bookly-faq-docs/policies/refunds.txt"}},
    },
]


def _event(query=None):
    return {"queryStringParameters": {"q": query} if query else None}


def test_missing_query_returns_400():
    resp = lambda_app.handler(_event(), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "missing_query"


def test_query_returns_ranked_matches(monkeypatch):
    fake = FakeBedrockClient(SAMPLE_RESULTS)
    monkeypatch.setattr(lambda_app, "client", fake)

    resp = lambda_app.handler(_event("how much is shipping"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["query"] == "how much is shipping"
    assert len(body["matches"]) == 2
    assert body["matches"][0]["score"] == 0.61
    assert "shipping.txt" in body["matches"][0]["source"]


def test_query_passed_through_to_bedrock_retrieve(monkeypatch):
    fake = FakeBedrockClient(SAMPLE_RESULTS)
    monkeypatch.setattr(lambda_app, "client", fake)

    lambda_app.handler(_event("what's your return policy"), None)
    assert fake.last_call["knowledgeBaseId"] == "test-kb-id"
    assert fake.last_call["retrievalQuery"] == {"text": "what's your return policy"}


def test_no_results_returns_404(monkeypatch):
    fake = FakeBedrockClient([])
    monkeypatch.setattr(lambda_app, "client", fake)

    resp = lambda_app.handler(_event("completely unrelated nonsense"), None)
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "no_match"
