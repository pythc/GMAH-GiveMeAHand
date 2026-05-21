"""MCP gateway HTTP routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent_workflow.api.dependencies import get_mcp_gateway
from agent_workflow.mcp.gateway import McpCallResult, McpCapability
from agent_workflow.mcp.http_gateway import StreamableHttpMcpGateway

router = APIRouter(prefix="/mcp", tags=["mcp"])
McpDep = Annotated[StreamableHttpMcpGateway, Depends(get_mcp_gateway)]


class McpToolCallRequest(BaseModel):
    server_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpResourceReadRequest(BaseModel):
    server_name: str
    resource_name: str


@router.get("/capabilities")
def list_capabilities(mcp_gateway: McpDep) -> list[McpCapability]:
    return mcp_gateway.list_capabilities()


@router.post("/tools/call")
def call_tool(request: McpToolCallRequest, mcp_gateway: McpDep) -> McpCallResult:
    return mcp_gateway.call_tool(request.server_name, request.tool_name, request.arguments)


@router.post("/resources/read")
def read_resource(request: McpResourceReadRequest, mcp_gateway: McpDep) -> McpCallResult:
    return mcp_gateway.read_resource(request.server_name, request.resource_name)
