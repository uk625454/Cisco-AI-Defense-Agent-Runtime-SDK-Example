from typing import TypedDict, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import jwt
import os

from aidefense.runtime import agentsec

# Select which AI Defense config file to use.
# Default is gateway mode if AGENTSEC_CONFIG_PATH is not set.
CONFIG_PATH = os.environ.get("AGENTSEC_CONFIG_PATH", "config/gateway/agentsec.yaml")

# IMPORTANT:
# protect() must run before importing boto3 so supported Bedrock calls
# are automatically patched by the Cisco AI Defense SDK.
agentsec.protect(config=CONFIG_PATH)

import boto3
from langgraph.graph import StateGraph, END

MODEL_ID = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
MODEL_REGION = "us-east-1"

# Supported Bedrock Runtime client.
# The SDK can patch supported methods like converse() on this path.
bedrock_runtime = boto3.client("bedrock-runtime", region_name=MODEL_REGION)

# FastAPI app served inside the custom AgentCore container runtime.
app = FastAPI(title="AgentCore LangGraph Agent", version="1.0.0")


class InvocationRequest(BaseModel):
    # Supports either {"prompt":"..."} or {"input":{"prompt":"..."}}.
    prompt: str | None = None
    input: Dict[str, Any] | None = None


class InvocationResponse(BaseModel):
    # Standard response returned by /invocations.
    response: str
    claims_seen: Dict[str, Any] | None = None


class AgentState(TypedDict):
    # Shared LangGraph state. In this simple example it is just the conversation.
    messages: List[Dict[str, Any]]


def call_model(state: AgentState) -> AgentState:
    # LangGraph reasoning node.
    # This Bedrock call is the supported path patched by the Cisco SDK.
    response = bedrock_runtime.converse(
        modelId=MODEL_ID,
        messages=state["messages"],
        inferenceConfig={
            "maxTokens": 512,
            "temperature": 0.2
        }
    )

    assistant_text = response["output"]["message"]["content"][0]["text"]

    # Update graph state by appending the assistant turn.
    return {
        "messages": state["messages"] + [
            {
                "role": "assistant",
                "content": [{"text": assistant_text}]
            }
        ]
    }


graph = StateGraph(AgentState)
graph.add_node("reasoning", call_model)
graph.set_entry_point("reasoning")
graph.add_edge("reasoning", END)
compiled_graph = graph.compile()


@app.get("/ping")
async def ping():
    # Health endpoint required by AgentCore custom runtimes.
    return {"status": "healthy"}


@app.post("/invocations", response_model=InvocationResponse)
async def invoke_agent(request: InvocationRequest, raw_request: Request):
    # Main runtime invocation endpoint required by AgentCore.

    prompt = request.prompt or ((request.input or {}).get("prompt"))
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")

    auth_header = raw_request.headers.get("authorization")
    claims = None
    if auth_header:
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
        # AgentCore already validated the JWT; this is only for optional visibility/debugging.
        claims = jwt.decode(token, options={"verify_signature": False})

    initial_state: AgentState = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ]
    }

    # Execute the LangGraph workflow:
    # initial_state -> reasoning node -> END.
    result = compiled_graph.invoke(initial_state)
    final_message = result["messages"][-1]["content"][0]["text"]

    return InvocationResponse(
        response=final_message,
        claims_seen=claims
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
