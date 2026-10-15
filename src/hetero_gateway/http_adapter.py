"""自定义 HTTP 适配器"""

import httpx
from .base import HeteroAdapter
from aip_adapter.models import AgentCard


class CustomHTTPAdapter(HeteroAdapter):
    """自定义 HTTP 服务适配器，将 HTTP 函数调用翻译为 AIP 能力"""

    def __init__(self, endpoint: str, functions: list[dict]):
        """
        初始化 HTTP 适配器

        Args:
            endpoint: 服务端点基础 URL
            functions: 函数列表，每项包含 {name, description, params}
                       params 格式: [{name, type, required}]
        """
        self.endpoint = endpoint.rstrip("/")
        self.functions = {func["name"]: func for func in functions}

    def to_agent_card(self) -> AgentCard:
        """将函数列表转换为 AgentCard"""
        capabilities = [func["name"] for func in self.functions.values()]

        return AgentCard(
            agent_id=f"http-{self.endpoint.split('//')[-1].split('/')[0]}",
            name=f"HTTP Service",
            description="自定义 HTTP 服务",
            capabilities=capabilities,
            endpoint=self.endpoint,
            protocol_version="http-1.0",
            metadata={"type": "http"},
        )

    def translate_invoke(self, aip_request: dict) -> dict:
        """
        将 AIP 请求翻译为 HTTP POST 请求

        AIP 请求格式: {capability: "function_name", params: {...}}
        HTTP 请求格式: 构造 httpx.Request 对象（不实际发送）

        返回请求摘要以便测试断言
        """
        capability = aip_request.get("capability")
        params = aip_request.get("params", {})

        if not capability:
            raise ValueError("AIP 请求缺少 capability 字段")

        if capability not in self.functions:
            raise ValueError(f"不存在函数: {capability}")

        func = self.functions[capability]

        # 参数校验
        param_defs = {p["name"]: p for p in func.get("params", [])}
        for param_name, param_def in param_defs.items():
            if param_def.get("required", False) and param_name not in params:
                raise ValueError(f"函数 {capability} 缺少必填参数: {param_name}")

        # 类型校验（与 mcp_adapter 保持一致）
        for param_name, param_value in params.items():
            if param_name not in param_defs:
                continue
            expected_type = param_defs[param_name].get("type")
            if not expected_type:
                continue

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

        # 构造 HTTP POST 请求
        url = f"{self.endpoint}/{capability}"
        request = httpx.Request(
            method="POST",
            url=url,
            json=params,
            headers={"Content-Type": "application/json"},
        )

        # 返回请求摘要（不实际发送）
        return {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": params,
            "summary": f"POST {url} with {len(params)} params",
        }

    def normalize_result(self, native_result) -> dict:
        """将 HTTP 响应归一化为 AIP 格式"""
        return {
            "ok": True,
            "data": native_result,
            "protocol": "http",
        }
