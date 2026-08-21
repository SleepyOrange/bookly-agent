#!/usr/bin/env bash
# Bootstraps the Bedrock Knowledge Base (S3 source docs -> Titan embeddings ->
# S3 Vectors index) that aws/faq_function/app.py retrieves against.
#
# Not in the SAM template: Knowledge Base + S3 Vectors aren't first-class
# CloudFormation resources with the same maturity as Lambda/API
# Gateway/DynamoDB, so this is scripted explicitly and idempotently instead
# of forced into IaC that doesn't reliably support them yet. Run this once
# before `sam deploy`, and pass its output KnowledgeBaseId as a parameter.
set -euo pipefail

REGION="eu-west-2"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
FAQ_BUCKET="bookly-faq-docs-${ACCOUNT_ID}"
VECTOR_BUCKET="bookly-faq-vectors"
VECTOR_INDEX="bookly-faq-index"
KB_ROLE_NAME="BooklyKnowledgeBaseRole"
EMBED_MODEL_ARN="arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v2:0"

echo "== 1. Source docs bucket =="
aws s3api create-bucket --bucket "$FAQ_BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" || true
aws s3api put-public-access-block --bucket "$FAQ_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "== 2. Generate + upload FAQ docs from external_service/data/policies.json =="
python3 - <<PYEOF
import json, pathlib
policies = json.load(open("external_service/data/policies.json"))
out = pathlib.Path("faq_docs")
out.mkdir(exist_ok=True)
for topic, text in policies.items():
    (out / f"{topic}.txt").write_text(f"Topic: {topic}\n\n{text}\n")
PYEOF
aws s3 sync faq_docs/ "s3://${FAQ_BUCKET}/policies/"

echo "== 3. Vector bucket + index =="
aws s3vectors create-vector-bucket --vector-bucket-name "$VECTOR_BUCKET" --region "$REGION" || true
aws s3vectors create-index \
  --vector-bucket-name "$VECTOR_BUCKET" \
  --index-name "$VECTOR_INDEX" \
  --data-type float32 \
  --dimension 1024 \
  --distance-metric cosine \
  --metadata-configuration '{"nonFilterableMetadataKeys":["AMAZON_BEDROCK_TEXT","AMAZON_BEDROCK_METADATA"]}' \
  --region "$REGION" || true

echo "== 4. IAM role for the Knowledge Base =="
cat > iam/kb-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "bedrock.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "aws:SourceAccount": "${ACCOUNT_ID}" } }
  }]
}
EOF
cat > iam/kb-permissions-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "InvokeEmbeddingModel", "Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "${EMBED_MODEL_ARN}" },
    { "Sid": "ReadSourceDocs", "Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::${FAQ_BUCKET}", "arn:aws:s3:::${FAQ_BUCKET}/*"] },
    { "Sid": "S3VectorsAccess", "Effect": "Allow",
      "Action": ["s3vectors:GetIndex","s3vectors:GetVectorBucket","s3vectors:PutVectors","s3vectors:GetVectors","s3vectors:QueryVectors","s3vectors:DeleteVectors","s3vectors:ListVectors"],
      "Resource": [
        "arn:aws:s3vectors:${REGION}:${ACCOUNT_ID}:bucket/${VECTOR_BUCKET}",
        "arn:aws:s3vectors:${REGION}:${ACCOUNT_ID}:bucket/${VECTOR_BUCKET}/index/${VECTOR_INDEX}"
      ] }
  ]
}
EOF
aws iam create-role --role-name "$KB_ROLE_NAME" --assume-role-policy-document file://iam/kb-trust-policy.json || true
aws iam put-role-policy --role-name "$KB_ROLE_NAME" --policy-name BooklyKBPermissions --policy-document file://iam/kb-permissions-policy.json
sleep 8  # let IAM propagate before Bedrock tries to assume the role

echo "== 5. Knowledge Base + data source + ingestion =="
KB_ID=$(aws bedrock-agent create-knowledge-base \
  --name bookly-faq-kb \
  --description "Bookly FAQ/policy knowledge base" \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/${KB_ROLE_NAME}" \
  --knowledge-base-configuration "{\"type\":\"VECTOR\",\"vectorKnowledgeBaseConfiguration\":{\"embeddingModelArn\":\"${EMBED_MODEL_ARN}\"}}" \
  --storage-configuration "{\"type\":\"S3_VECTORS\",\"s3VectorsConfiguration\":{\"vectorBucketArn\":\"arn:aws:s3vectors:${REGION}:${ACCOUNT_ID}:bucket/${VECTOR_BUCKET}\",\"indexArn\":\"arn:aws:s3vectors:${REGION}:${ACCOUNT_ID}:bucket/${VECTOR_BUCKET}/index/${VECTOR_INDEX}\"}}" \
  --region "$REGION" --query "knowledgeBase.knowledgeBaseId" --output text)
echo "Knowledge Base ID: $KB_ID"

DS_ID=$(aws bedrock-agent create-data-source \
  --knowledge-base-id "$KB_ID" \
  --name bookly-faq-docs-source \
  --data-source-configuration "{\"type\":\"S3\",\"s3Configuration\":{\"bucketArn\":\"arn:aws:s3:::${FAQ_BUCKET}\",\"inclusionPrefixes\":[\"policies/\"]}}" \
  --vector-ingestion-configuration '{"chunkingConfiguration":{"chunkingStrategy":"FIXED_SIZE","fixedSizeChunkingConfiguration":{"maxTokens":300,"overlapPercentage":20}}}' \
  --region "$REGION" --query "dataSource.dataSourceId" --output text)

JOB_ID=$(aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" --region "$REGION" --query "ingestionJob.ingestionJobId" --output text)
echo "Ingestion job $JOB_ID started -- poll with:"
echo "  aws bedrock-agent get-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DS_ID --ingestion-job-id $JOB_ID --region $REGION"

echo ""
echo "Done. Deploy the REST API stack with:"
echo "  sam build && sam deploy --stack-name bookly-external-api --resolve-s3 --region $REGION --capabilities CAPABILITY_IAM --parameter-overrides KnowledgeBaseId=$KB_ID"
