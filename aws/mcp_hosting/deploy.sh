#!/usr/bin/env bash
# Deploys external_service/mcp_server.py to AWS App Runner, with API Gateway
# in front enforcing an API key. No local Docker required -- the image is
# built by AWS CodeBuild from a zipped source upload, since this environment
# didn't have a Docker daemon available; CodeBuild's build environment has
# one built in (privilegedMode=true) and it's arguably more consistent with
# everything else in this project being AWS-native anyway.
#
# Run from the repo root: aws/mcp_hosting/deploy.sh
set -euo pipefail

REGION="eu-west-2"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REPO="bookly-mcp-server"
BUILD_BUCKET="bookly-build-artifacts-${ACCOUNT_ID}"
ORIGIN_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

echo "== 1. ECR repository =="
aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" \
  --image-scanning-configuration scanOnPush=true || true

echo "== 2. Build source: zip + upload to S3 =="
aws s3api create-bucket --bucket "$BUILD_BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" || true
aws s3api put-public-access-block --bucket "$BUILD_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
zip -r /tmp/mcp-build-source.zip Dockerfile.mcp external_service/ \
  -x "external_service/__pycache__/*" -x "external_service/data/__pycache__/*"
aws s3 cp /tmp/mcp-build-source.zip "s3://${BUILD_BUCKET}/mcp-build-source.zip"

echo "== 3. CodeBuild: role + project =="
cat > aws/mcp_hosting/iam/codebuild-trust-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
cat > aws/mcp_hosting/iam/codebuild-permissions-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/codebuild/bookly-mcp-build*" },
    { "Sid": "S3Source", "Effect": "Allow", "Action": ["s3:GetObject","s3:GetObjectVersion"], "Resource": "arn:aws:s3:::${BUILD_BUCKET}/*" },
    { "Sid": "EcrAuth", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    { "Sid": "EcrPush", "Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability","ecr:PutImage","ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"], "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/${ECR_REPO}" }
  ]
}
EOF
aws iam create-role --role-name BooklyMcpCodeBuildRole --assume-role-policy-document file://aws/mcp_hosting/iam/codebuild-trust-policy.json || true
aws iam put-role-policy --role-name BooklyMcpCodeBuildRole --policy-name BooklyMcpCodeBuildPermissions --policy-document file://aws/mcp_hosting/iam/codebuild-permissions-policy.json
sleep 8  # let IAM propagate

python3 -c "
import json
buildspec = f'''version: 0.2
phases:
  pre_build:
    commands:
      - aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com
  build:
    commands:
      - docker build -f Dockerfile.mcp -t ${ECR_REPO}:latest .
      - docker tag ${ECR_REPO}:latest ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest
  post_build:
    commands:
      - docker push ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest
'''
payload = {
    'name': 'bookly-mcp-build',
    'source': {'type': 'S3', 'location': '${BUILD_BUCKET}/mcp-build-source.zip', 'buildspec': buildspec},
    'artifacts': {'type': 'NO_ARTIFACTS'},
    'environment': {'type': 'LINUX_CONTAINER', 'image': 'aws/codebuild/standard:7.0', 'computeType': 'BUILD_GENERAL1_SMALL', 'privilegedMode': True},
    'serviceRole': 'arn:aws:iam::${ACCOUNT_ID}:role/BooklyMcpCodeBuildRole',
}
json.dump(payload, open('/tmp/codebuild-project.json', 'w'))
"
aws codebuild create-project --cli-input-json file:///tmp/codebuild-project.json --region "$REGION" || \
  aws codebuild update-project --cli-input-json file:///tmp/codebuild-project.json --region "$REGION"

echo "== 4. Run the build =="
BUILD_ID=$(aws codebuild start-build --project-name bookly-mcp-build --region "$REGION" --query "build.id" --output text)
echo "Build: $BUILD_ID"
while true; do
  STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --region "$REGION" --query "builds[0].buildStatus" --output text)
  echo "  status=$STATUS"
  [ "$STATUS" != "IN_PROGRESS" ] && break
  sleep 15
done
[ "$STATUS" = "SUCCEEDED" ] || { echo "Build failed, check CloudWatch Logs: /aws/codebuild/bookly-mcp-build"; exit 1; }

echo "== 5. App Runner service =="
cat > aws/mcp_hosting/iam/apprunner-ecr-trust-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
aws iam create-role --role-name BooklyAppRunnerEcrAccessRole --assume-role-policy-document file://aws/mcp_hosting/iam/apprunner-ecr-trust-policy.json || true
aws iam attach-role-policy --role-name BooklyAppRunnerEcrAccessRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess || true

python3 -c "
import json
payload = {
    'ServiceName': 'bookly-mcp-server',
    'SourceConfiguration': {
        'AuthenticationConfiguration': {'AccessRoleArn': 'arn:aws:iam::${ACCOUNT_ID}:role/BooklyAppRunnerEcrAccessRole'},
        'ImageRepository': {
            'ImageIdentifier': '${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest',
            'ImageRepositoryType': 'ECR',
            'ImageConfiguration': {'Port': '8200', 'RuntimeEnvironmentVariables': {'MCP_ORIGIN_SECRET': '${ORIGIN_SECRET}'}},
        },
        'AutoDeploymentsEnabled': False,
    },
    'InstanceConfiguration': {'Cpu': '0.25 vCPU', 'Memory': '0.5 GB'},
}
json.dump(payload, open('/tmp/apprunner-create.json', 'w'))
"
APPRUNNER_RESULT=$(aws apprunner create-service --cli-input-json file:///tmp/apprunner-create.json --region "$REGION")
APPRUNNER_ARN=$(echo "$APPRUNNER_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['Service']['ServiceArn'])")
APPRUNNER_URL=$(echo "$APPRUNNER_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['Service']['ServiceUrl'])")
echo "App Runner deploying: https://${APPRUNNER_URL}"
while true; do
  STATUS=$(aws apprunner describe-service --service-arn "$APPRUNNER_ARN" --region "$REGION" --query "Service.Status" --output text)
  echo "  status=$STATUS"
  [ "$STATUS" = "RUNNING" ] || [ "$STATUS" = "CREATE_FAILED" ] && break
  sleep 15
done

echo "== 6. API Gateway: auth in front of App Runner =="
API_ID=$(aws apigateway create-rest-api --name bookly-mcp-gateway --region "$REGION" --query "id" --output text)
ROOT_ID=$(aws apigateway get-resources --rest-api-id "$API_ID" --region "$REGION" --query "items[0].id" --output text)
PROXY_RES=$(aws apigateway create-resource --rest-api-id "$API_ID" --parent-id "$ROOT_ID" --path-part "{proxy+}" --region "$REGION" --query "id" --output text)
aws apigateway put-method --rest-api-id "$API_ID" --resource-id "$PROXY_RES" --http-method ANY \
  --authorization-type NONE --api-key-required --request-parameters "method.request.path.proxy=true" --region "$REGION"
python3 -c "
import json
payload = {
    'restApiId': '${API_ID}', 'resourceId': '${PROXY_RES}', 'httpMethod': 'ANY',
    'type': 'HTTP_PROXY', 'integrationHttpMethod': 'ANY',
    'uri': 'https://${APPRUNNER_URL}/{proxy}',
    'requestParameters': {
        'integration.request.path.proxy': 'method.request.path.proxy',
        'integration.request.header.X-Origin-Secret': \"'${ORIGIN_SECRET}'\",
    },
}
json.dump(payload, open('/tmp/put-integration.json', 'w'))
"
aws apigateway put-integration --cli-input-json file:///tmp/put-integration.json --region "$REGION"
aws apigateway create-deployment --rest-api-id "$API_ID" --stage-name prod --region "$REGION"

API_KEY_RESULT=$(aws apigateway create-api-key --name bookly-mcp-agent-key --enabled --region "$REGION")
API_KEY_ID=$(echo "$API_KEY_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
API_KEY_VALUE=$(echo "$API_KEY_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['value'])")
USAGE_PLAN_ID=$(aws apigateway create-usage-plan --name bookly-mcp-usage-plan --api-stages "apiId=${API_ID},stage=prod" --region "$REGION" --query "id" --output text)
aws apigateway create-usage-plan-key --usage-plan-id "$USAGE_PLAN_ID" --key-id "$API_KEY_ID" --key-type API_KEY --region "$REGION" > /dev/null

echo ""
echo "Done. Point the agent at the hosted MCP server with:"
echo "  export BOOKLY_TRANSPORT=mcp"
echo "  export BOOKLY_MCP_SERVER_URL=https://${API_ID}.execute-api.${REGION}.amazonaws.com/prod/mcp"
echo "  export BOOKLY_MCP_API_KEY=${API_KEY_VALUE}"
