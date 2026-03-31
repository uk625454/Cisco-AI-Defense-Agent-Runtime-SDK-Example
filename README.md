# AgentCore LangGraph + Cisco AI Defense Runtime SDK Example

This repository shows a simple, container-based AWS Bedrock AgentCore Runtime agent built with LangGraph and protected by the Cisco AI Defense Runtime SDK.

This example does **not** use MCP. The runtime protection is applied to Bedrock model calls made from the LangGraph reasoning node. Because MCP is not part of this example, you do **not** need MCP environment variables here.

It includes two supported AI Defense runtime modes:

- **Gateway mode** using `config/gateway/agentsec.yaml`
- **API enforce mode** using `config/api-enforce/agentsec.yaml`

The file name stays `agentsec.yaml` in both cases. You switch modes by changing the `AGENTSEC_CONFIG_PATH` environment variable.

---

## Architecture

```text
User / client
  → HTTPS invoke to AgentCore Runtime
  → AgentCore Runtime
  → Containerized FastAPI app
  → LangGraph workflow
  → reasoning node
  → boto3 bedrock-runtime.converse()
  → Cisco AI Defense Runtime SDK patch
      → Gateway mode: proxy through AI Defense Gateway
      → API mode: inspect request/response through AI Defense API
  → Amazon Bedrock model
```

---

## Why the Cisco SDK integrates where it does

The Cisco AI Defense Runtime SDK is designed to patch supported client libraries **before** those libraries are imported by your application.

That is why `agent.py` does this near the top:

```python
from aidefense.runtime import agentsec
agentsec.protect(config=CONFIG_PATH)

import boto3
```

This matters because:

- `protect()` loads the SDK configuration from `agentsec.yaml`
- `protect()` installs runtime hooks / patches
- then later-imported supported clients use the patched path automatically

For Amazon Bedrock, the supported patched `boto3` methods are:

- `bedrock-runtime.converse()`
- `bedrock-runtime.converse_stream()`

This does **not** mean all of `boto3` is patched. It means the SDK supports specific Bedrock Runtime methods.

In this repo, the LangGraph reasoning node calls `bedrock_runtime.converse(...)`, which is the supported path the Cisco SDK can intercept.

---

## Gateway mode vs API enforce mode

### Gateway mode

In gateway mode:

- your code still calls `boto3.client("bedrock-runtime").converse(...)`
- the Cisco SDK intercepts that Bedrock call
- the call is routed through the configured AI Defense gateway
- gateway-side policy decides allow/block behavior

Use config path:

```text
config/gateway/agentsec.yaml
```

### API enforce mode

In API enforce mode:

- your code still calls `boto3.client("bedrock-runtime").converse(...)`
- the Cisco SDK inspects request/response through the AI Defense inspection API
- the provider call still uses the direct provider client path
- local SDK-side enforcement raises a security exception on violations

Use config path:

```text
config/api-enforce/agentsec.yaml
```

---

## Repository layout

```text
agentcore-langgraph-aidefense/
├── README.md
├── requirements.txt
├── Dockerfile
├── .env.example
├── agent.py
├── deploy_agent.py
└── config/
    ├── gateway/
    │   └── agentsec.yaml
    └── api-enforce/
        └── agentsec.yaml
```

---

## What each file does

### `agent.py`

This is the runtime application that AgentCore executes inside the container.

It is responsible for:

- loading Cisco AI Defense runtime protection
- creating the Bedrock client
- building the LangGraph workflow
- exposing `/ping` and `/invocations` for AgentCore
- invoking the reasoning node and returning the final response

The file itself contains inline comments explaining each section.

### `deploy_agent.py`

This is the AWS control-plane deployment script.

It is responsible for:

- creating the AgentCore Runtime resource
- pointing it to the ECR container image
- injecting runtime environment variables into the container
- configuring JWT bearer-token auth with Cognito
- forwarding the `Authorization` header into the container
- setting lifecycle/session settings

The file itself contains inline comments explaining each section.

### `config/gateway/agentsec.yaml`

Gateway-mode Cisco AI Defense configuration.

### `config/api-enforce/agentsec.yaml`

API enforce-mode Cisco AI Defense configuration.

### `Dockerfile`

Builds the custom AgentCore runtime container.

### `requirements.txt`

Defines Python dependencies used inside the container.

### `.env.example`

Shows the environment variables required for local testing and deployment.

---

## Do we need MCP variables here?

No. This example is not using MCP integration, MCP tool traffic, or MCP servers. So for this repo:

- you do **not** need MCP-specific environment variables
- you do **not** need MCP-specific YAML sections
- you do **not** need MCP-related runtime setup steps

If you later extend this project to use MCP tools, you can add those settings back intentionally.

---

## Prerequisites

Before you begin in AWS CloudShell, make sure you have:

- an AWS account with access to Amazon Bedrock AgentCore
- permission to create or use an ECR repository
- permission to create or use a Cognito user pool and app client
- permission to create or use an IAM execution role for AgentCore Runtime
- a Cisco AI Defense gateway URL and API key if using gateway mode
- a Cisco AI Defense inspection endpoint and API key if using API enforce mode

---

## Step-by-step from AWS CloudShell

These steps assume you are starting from AWS CloudShell and do **not** already have Cognito configured.

### 1. Prepare CloudShell

```bash
mkdir -p ~/agentcore-langgraph-aidefense
cd ~/agentcore-langgraph-aidefense

aws sts get-caller-identity
aws configure get region

export REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

sudo dnf install -y python3.11 python3.11-pip jq zip docker
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install boto3
```

### 2. Put the repo in CloudShell

If you cloned this repo from GitHub:

```bash
git clone <YOUR_REPO_URL>
cd agentcore-langgraph-aidefense
```

If you uploaded the repo zip to CloudShell, unzip it and enter the project directory.

### 3. Create an ECR repository if you do not already have one

```bash
export ECR_REPO_NAME=agentcore-langgraph-sdk

aws ecr describe-repositories \
  --repository-names "$ECR_REPO_NAME" \
  --region "$REGION" >/dev/null 2>&1 || \
aws ecr create-repository \
  --repository-name "$ECR_REPO_NAME" \
  --region "$REGION"

export CONTAINER_URI=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO_NAME}:latest
```

### 4. Build and push the container image

```bash
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

docker build -t ${ECR_REPO_NAME}:latest .
docker tag ${ECR_REPO_NAME}:latest ${CONTAINER_URI}
docker push ${CONTAINER_URI}
```

### 5. Create Cognito for bearer-token auth

This sets up a simple Cognito user pool, app client, and test user so AgentCore Runtime can validate inbound JWT bearer tokens.

```bash
export USERNAME=testuser
export PASSWORD='YourStrongPassw0rd!'

export POOL_ID=$(aws cognito-idp create-user-pool \
  --pool-name "AgentCoreBearerDemoPool" \
  --policies '{"PasswordPolicy":{"MinimumLength":8}}' \
  --region "$REGION" | jq -r '.UserPool.Id')

export CLIENT_ID=$(aws cognito-idp create-user-pool-client \
  --user-pool-id "$POOL_ID" \
  --client-name "AgentCoreBearerDemoClient" \
  --no-generate-secret \
  --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" \
  --region "$REGION" | jq -r '.UserPoolClient.ClientId')

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username "$USERNAME" \
  --region "$REGION" \
  --message-action SUPPRESS

aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  --region "$REGION" \
  --permanent

export DISCOVERY_URL="https://cognito-idp.${REGION}.amazonaws.com/${POOL_ID}/.well-known/openid-configuration"

export BEARER_TOKEN=$(aws cognito-idp initiate-auth \
  --client-id "$CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME="$USERNAME",PASSWORD="$PASSWORD" \
  --region "$REGION" | jq -r '.AuthenticationResult.AccessToken')
```

### 6. Set your AgentCore execution role

Use an existing AgentCore execution role if you already have one.

```bash
export EXECUTION_ROLE_ARN=arn:aws:iam::${ACCOUNT_ID}:role/REPLACE_WITH_YOUR_AGENTCORE_EXECUTION_ROLE
```

If you do not already have that role, create it in IAM first, then come back and export the ARN.

### 7. Choose your AI Defense mode

#### Gateway mode

```bash
export AGENTSEC_CONFIG_PATH=config/gateway/agentsec.yaml
export AI_DEFENSE_BEDROCK_GATEWAY_URL='https://REPLACE_WITH_YOUR_GATEWAY_URL'
export AI_DEFENSE_BEDROCK_GATEWAY_API_KEY='REPLACE_WITH_YOUR_GATEWAY_API_KEY'
```

#### API enforce mode

```bash
export AGENTSEC_CONFIG_PATH=config/api-enforce/agentsec.yaml
export AI_DEFENSE_API_MODE_LLM_ENDPOINT='https://REPLACE_WITH_YOUR_INSPECTION_ENDPOINT'
export AI_DEFENSE_API_MODE_LLM_API_KEY='REPLACE_WITH_YOUR_INSPECTION_API_KEY'
```

### 8. Deploy the AgentCore Runtime

```bash
python deploy_agent.py
```

Capture the runtime ARN printed by the script.

```bash
export AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:REPLACE_WITH_REAL_RUNTIME_ARN'
```

### 9. URL-encode the runtime ARN

```bash
export ESCAPED_AGENT_ARN=$(python3 -c "import urllib.parse, os; print(urllib.parse.quote(os.environ['AGENT_RUNTIME_ARN'], safe=''))")
```

### 10. Invoke the runtime with the bearer token

```bash
curl -X POST "https://bedrock-agentcore.${REGION}.amazonaws.com/runtimes/${ESCAPED_AGENT_ARN}/invocations?qualifier=DEFAULT" \
  -H "Authorization: Bearer ${BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: session-001" \
  -d '{"prompt":"In one sentence, what is LangGraph?"}'
```

---

## Local testing

You can also run the container locally before pushing it.

### Build locally

```bash
docker build -t agentcore-langgraph-sdk:local .
```

### Run locally

Gateway mode example:

```bash
docker run --rm -p 8080:8080 \
  -e AGENTSEC_CONFIG_PATH=config/gateway/agentsec.yaml \
  -e AI_DEFENSE_BEDROCK_GATEWAY_URL="$AI_DEFENSE_BEDROCK_GATEWAY_URL" \
  -e AI_DEFENSE_BEDROCK_GATEWAY_API_KEY="$AI_DEFENSE_BEDROCK_GATEWAY_API_KEY" \
  -e AWS_REGION="$REGION" \
  agentcore-langgraph-sdk:local
```

API enforce mode example:

```bash
docker run --rm -p 8080:8080 \
  -e AGENTSEC_CONFIG_PATH=config/api-enforce/agentsec.yaml \
  -e AI_DEFENSE_API_MODE_LLM_ENDPOINT="$AI_DEFENSE_API_MODE_LLM_ENDPOINT" \
  -e AI_DEFENSE_API_MODE_LLM_API_KEY="$AI_DEFENSE_API_MODE_LLM_API_KEY" \
  -e AWS_REGION="$REGION" \
  agentcore-langgraph-sdk:local
```

Then invoke locally:

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hello from local Docker"}'
```

---

## Notes

- `agent.py` and `deploy_agent.py` contain inline explanatory comments, so the README does not repeat their full annotated contents.
- This example uses JWT bearer-token auth through Cognito for the AgentCore Runtime invocation path.
- This example does not use MCP, so MCP settings were intentionally removed.
