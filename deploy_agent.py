import os
import boto3

# Deployment-time values read from the current shell environment.
REGION = os.environ["REGION"]
ACCOUNT_ID = os.environ["ACCOUNT_ID"]
CONTAINER_URI = os.environ["CONTAINER_URI"]
DISCOVERY_URL = os.environ["DISCOVERY_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
EXECUTION_ROLE_ARN = os.environ["EXECUTION_ROLE_ARN"]

# AgentCore control-plane client used to create the runtime.
client = boto3.client("bedrock-agentcore-control", region_name=REGION)

environment_variables = {
    "AGENTSEC_CONFIG_PATH": os.environ.get("AGENTSEC_CONFIG_PATH", "config/gateway/agentsec.yaml"),
    "AWS_REGION": REGION,
}

# Gateway mode variables are only needed if you are using gateway mode.
if os.environ.get("AI_DEFENSE_BEDROCK_GATEWAY_URL"):
    environment_variables["AI_DEFENSE_BEDROCK_GATEWAY_URL"] = os.environ["AI_DEFENSE_BEDROCK_GATEWAY_URL"]
if os.environ.get("AI_DEFENSE_BEDROCK_GATEWAY_API_KEY"):
    environment_variables["AI_DEFENSE_BEDROCK_GATEWAY_API_KEY"] = os.environ["AI_DEFENSE_BEDROCK_GATEWAY_API_KEY"]

# API enforce mode variables are only needed if you are using API mode.
if os.environ.get("AI_DEFENSE_API_MODE_LLM_ENDPOINT"):
    environment_variables["AI_DEFENSE_API_MODE_LLM_ENDPOINT"] = os.environ["AI_DEFENSE_API_MODE_LLM_ENDPOINT"]
if os.environ.get("AI_DEFENSE_API_MODE_LLM_API_KEY"):
    environment_variables["AI_DEFENSE_API_MODE_LLM_API_KEY"] = os.environ["AI_DEFENSE_API_MODE_LLM_API_KEY"]

response = client.create_agent_runtime(
    agentRuntimeName="langgraph_sdk_container_agent",
    # Logical name of the runtime resource in AgentCore.
    agentRuntimeArtifact={
        "containerConfiguration": {
            "containerUri": CONTAINER_URI
        }
    },
    # Tells AgentCore to run the specified ECR image.
    networkConfiguration={"networkMode": "PUBLIC"},
    # Runtime network mode.
    roleArn=EXECUTION_ROLE_ARN,
    # IAM execution role for the runtime.
    authorizerConfiguration={
        "customJWTAuthorizer": {
            "discoveryUrl": DISCOVERY_URL,
            "allowedClients": [CLIENT_ID]
        }
    },
    # Configures JWT bearer auth using Cognito OIDC metadata.
    requestHeaderConfiguration={
        "requestHeaderAllowlist": ["Authorization"]
    },
    # Allows the Authorization header to be forwarded into the container.
    environmentVariables=environment_variables,
    # Injects only the runtime configuration values this example needs.
    lifecycleConfiguration={
        "idleRuntimeSessionTimeout": 300,
        "maxLifetime": 1800
    }
    # Session/runtime lifecycle settings.
)

print("✅ Agent Runtime created successfully")
print("Agent Runtime ARN:", response["agentRuntimeArn"])
print("Status:", response["status"])
