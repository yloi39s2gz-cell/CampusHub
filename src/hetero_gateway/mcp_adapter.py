"""MCP (Model Context Protocol) 适配器"""

from .base import HeteroAdapter
from aip_adapter.models import AgentCard


class MCPAdapter(HeteroAdapter):
    """MCP 协议适配器，将 MCP server 的工具翻译为 AIP 能力"""

    def __init__(self, server_name: str, tools: list[dict]):
        """
        初始化 MCP 适配器

        Args:
            server_name: MCP 服务器名称
            tools: 工具列表，每项包含 {name, description, input_schema}
                   input_schema 格式: {type: "object", properties: {...}, required: [...]}
        """
        self.server_name = server_name
        self.tools = {tool["name"]: tool for tool in tools}

    def to_agent_card(self) -> AgentCard:
        """将 MCP 工具列表转换为 AgentCard，每个工具作为一个能力"""
        capabilities = [tool["name"] for tool in self.tools.values()]

        return AgentCard(
            agent_id=f"mcp-{self.server_name}",
            name=f"MCP-{self.server_name}",
            description=f"MCP 服务器 {self.server_name} 提供的工具集",
            capabilities=capabilities,
            endpoint=f"mcp://{self.server_name}",
            protocol_version="mcp-1.0",
            metadata={"type": "mcp", "server_name": self.server_name},
        )

    def translate_invoke(self, aip_request: dict) -> dict:
        """
        将 AIP 请求翻译为 MCP tool 调用

        AIP 请求格式: {capability: "tool_name", params: {...}}
        MCP 请求格式: {tool: "tool_name", arguments: {...}}

        包含必填参数校验与类型粗校验
        """
        capability = aip_request.get("capability")
        params = aip_request.get("params", {})

        if not capability:
            raise ValueError("AIP 请求缺少 capability 字段")

        if capability not in self.tools:
            raise ValueError(f"MCP 服务器 {self.server_name} 不存在工具 {capability}")

        tool = self.tools[capability]
        input_schema = tool.get("input_schema", {})

        # 必填参数校验
        required = input_schema.get("required", [])
        for req_param in required:
            if req_param not in params:
                raise ValueError(f"工具 {capability} 缺少必填参数: {req_param}")

        # 类型粗校验
        properties = input_schema.get("properties", {})
        for param_name, param_value in params.items():
            if param_name not in properties:
                continue

            expected_type = properties[param_name].get("type")
            if not expected_type:
                continue

            # 简单的类型检查
            if expected_type == "string" and not isinstance(param_value, str):
                raise ValueError(
                    f"参数 {param_name} 应为 string 类型，实际为 {type(param_value).__name__}"
                )
            elif expected_type == "integer" and not isinstance(param_value, int):
                raise ValueError(
                    f"参数 {param_name} 应为 integer 类型，实际为 {type(param_value).__name__}"
                )
            elif expected_type == "number" and not isinstance(param_value, (int, float)):
                raise ValueError(
                    f"参数 {param_name} 应为 number 类型，实际为 {type(param_value).__name__}"
                )
            elif expected_type == "boolean" and not isinstance(param_value, bool):
                raise ValueError(
                    f"参数 {param_name} 应为 boolean 类型，实际为 {type(param_value).__name__}"
                )

        # 翻译为 MCP 格式
        return {
            "tool": capability,
            "arguments": params,
        }

    def normalize_result(self, native_result) -> dict:
        """将 MCP 结果归一化为 AIP 格式

        MCP 协议规范中，工具结果可能包含 isError 字段标识调用是否失败。
        需要检查该字段并正确设置 ok 状态。
        """
        # 检查 MCP 协议规范中的 isError 字段
        is_error = False
        if isinstance(native_result, dict):
            is_error = native_result.get("isError", False)

        return {
            "ok": not is_error,
            "data": native_result,
            "protocol": "mcp",
        }
