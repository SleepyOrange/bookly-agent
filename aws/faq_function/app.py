"""FAQ Lambda -- real semantic retrieval against the Bedrock Knowledge Base
(bookly-faq-kb), backed by S3 Vectors. Replaces the exact-topic lookup with
a free-text query: this is the actual RAG pattern (ingest once via the KB's
data source, retrieve by meaning at query time), matching how Decagon
describes syncing Confluence/Contentful into an agent's knowledge base.
"""
import json
import os

import boto3

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
NUM_RESULTS = int(os.environ.get("NUM_RESULTS", "3"))

client = boto3.client("bedrock-agent-runtime")


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    query = (event.get("queryStringParameters") or {}).get("q", "").strip()
    if not query:
        return _response(400, {"error": "missing_query", "message": "Provide a query via ?q=..."})

    result = client.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": NUM_RESULTS}},
    )

    matches = [
        {
            "text": r["content"]["text"],
            "score": r["score"],
            "source": r.get("location", {}).get("s3Location", {}).get("uri"),
        }
        for r in result.get("retrievalResults", [])
    ]

    if not matches:
        return _response(404, {"error": "no_match", "message": "No relevant policy content found."})

    return _response(200, {"query": query, "matches": matches})
